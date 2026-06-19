# -*- coding: utf-8 -*-
"""gfam_index_cache.py -- 统一 Index/index 缓存管理器

设计目标：
    1. 消除同一执行流中的冗余 Index/index 请求
    2. 提供线程安全的 TTL 缓存
    3. 兼容现有 .gfam_index_cache.json 共享缓存（跨进程）
    4. 不修改任何模块的核心业务逻辑

接入方式：
    manager = IndexCacheManager(client, ttl=60)
    payload = manager.get()           # TTL 内复用，过期则自动请求
    payload = manager.get(force=True) # 强制刷新
    manager.bypass(client, "emergency")  # 不走缓存，直接请求

线程安全：
    所有公开方法均通过 threading.Lock 保护。
    内部 _payload 和 _fetched_at 的读写是原子性的（在锁内）。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# 尝试导入 gflzirc；如果不在 PYTHONPATH 中则静默降级
# ---------------------------------------------------------------------------
try:
    from gflzirc import GFLClient, API_INDEX_INDEX
except Exception:
    GFLClient = None
    API_INDEX_INDEX = "Index/index"

try:
    from gfam_api_lock import patch_gfl_client
    patch_gfl_client()
except Exception:
    pass

# ---------------------------------------------------------------------------
# 共享文件缓存常量（与 factory_auto / factory_config 保持一致）
# ---------------------------------------------------------------------------
SHARED_INDEX_FILE = ".gfam_index_cache.json"
SHARED_INDEX_TTL_ENV = "GFAM_SHARED_INDEX_TTL"
DEFAULT_SHARED_TTL = 300  # 秒（与 factory 模块一致）


class IndexCacheManager:
    """线程安全的 Index/index 响应缓存管理器。

    典型生命周期（以 EPA 模块为例）::

        # 模块启动时创建（-a 命令触发）
        mgr = IndexCacheManager(client, ttl=60, label="EPA")

        # E1：用户 -a 时获取
        payload = mgr.get()           # 发送请求，缓存 payload

        # ... 用户选择关卡、目标 ...

        # E2：用户 -r 时刷新 Micro 上限
        payload = mgr.get()           # TTL 内命中缓存，不发送请求
        # 或者，如果确实需要最新数据：
        payload = mgr.get(force=True) # 强制刷新

        # E3：夜战装备锁验证 -- 必须 bypass
        payload = mgr.bypass(client, reason="equip_lock_verify")

        # E4：错误恢复 -- 必须 bypass（服务端状态可能已变）
        payload = mgr.bypass(client, reason="safe_abort_sync")
    """

    def __init__(
        self,
        client: Any,
        *,
        ttl: int = 60,
        label: str = "IndexCache",
        shared_file: Optional[str] = None,
        shared_ttl: Optional[int] = None,
        root_dir: Optional[Path] = None,
    ) -> None:
        """
        Args:
            client:      GFLClient 实例（用于发送请求）。
            ttl:         内存缓存的 TTL 秒数。默认 60 秒。
                         EPA/13-4/Smart 推荐 60-120 秒。
                         Pick & Train 推荐 30 秒（coin 变化快）。
            label:       日志标签前缀，便于调试。
            shared_file: 共享 JSON 缓存文件路径。None 表示不读写共享文件。
                         传入 ".gfam_index_cache.json" 可与 factory 模块共享。
            shared_ttl:  共享文件缓存的 TTL 秒数。默认 300（与 factory 一致）。
            root_dir:    项目根目录，用于定位共享缓存文件。
        """
        self._client = client
        self._ttl = max(1, int(ttl))
        self._label = label

        # 内存缓存状态
        self._lock = threading.Lock()
        self._payload: Optional[Dict[str, Any]] = None
        self._fetched_at: float = 0.0
        self._source: str = "none"
        self._fetch_count: int = 0  # 统计：实际网络请求次数

        # 共享文件缓存
        self._shared_file = shared_file
        self._shared_ttl = max(1, int(shared_ttl or DEFAULT_SHARED_TTL))
        self._root_dir = root_dir or Path.cwd()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def get(self, *, force: bool = False, reason: str = "") -> Optional[Dict[str, Any]]:
        """获取 Index/index 响应，优先使用缓存。

        调用顺序：
            1. 如果 force=False 且内存缓存未过期 → 直接返回
            2. 如果 force=False 且共享文件缓存未过期 → 加载并返回
            3. 发送网络请求 → 缓存结果 → 写入共享文件 → 返回

        Args:
            force:  为 True 时跳过所有缓存层，强制发送网络请求。
            reason: 调用原因，仅用于日志。

        Returns:
            Index/index 的响应 dict，失败返回 None。
        """
        with self._lock:
            # ① 内存缓存命中
            if not force and self._payload is not None:
                age = time.time() - self._fetched_at
                if age <= self._ttl:
                    self._log(f"内存缓存命中 (age={age:.0f}s, ttl={self._ttl}s) {reason}")
                    return self._payload
                else:
                    self._log(f"内存缓存过期 (age={age:.0f}s > ttl={self._ttl}s) {reason}")

            # ② 共享文件缓存命中（仅在非强制模式）
            if not force:
                shared_payload = self._read_shared_cache()
                if shared_payload is not None:
                    self._payload = shared_payload
                    self._fetched_at = time.time()
                    self._source = "shared_file"
                    self._log(f"共享文件缓存命中 {reason}")
                    return self._payload

            # ③ 发送网络请求
            return self._do_fetch(reason or ("force" if force else "cache_miss"))

    def bypass(self, client: Any = None, *, reason: str = "") -> Optional[Dict[str, Any]]:
        """绕过缓存，直接发送 Index/index 请求。

        用于以下场景（这些场景必须获取最新数据）：
            - E3/S3：夜战装备锁验证（changeLock 后立即检查）
            - E4/S4/T4：gfam_safe_abort_and_sync（错误后服务端状态可能已变）
            - E2/T3/S2：emergency_retire（仓库满时需要最新列表）
            - P3：gfam_try_exception_self_repair（Micro 失败后找拆解候选）

        请求成功后会更新内存缓存（因为拿到了最新数据），但不写入共享文件
        （避免其他模块拿到一个"错误恢复时刻"的快照作为基准）。

        Args:
            client: 可覆盖默认 client。为 None 时使用构造时的 client。
            reason: 调用原因，用于日志。

        Returns:
            最新响应 dict，失败返回 None。
        """
        use_client = client or self._client
        with self._lock:
            return self._do_fetch(reason or "bypass", client=use_client, update_shared=False)

    def peek(self) -> Tuple[Optional[Dict[str, Any]], float]:
        """只读查看当前缓存状态，不触发请求。

        Returns:
            (payload, fetched_at) 元组。如果无缓存则 (None, 0.0)。
        """
        with self._lock:
            return self._payload, self._fetched_at

    def invalidate(self) -> None:
        """手动清除内存缓存（不影响共享文件）。"""
        with self._lock:
            self._payload = None
            self._fetched_at = 0.0
            self._source = "invalidated"
            self._log("内存缓存已手动清除")

    @property
    def fetch_count(self) -> int:
        """统计：本管理器生命周期内的实际网络请求次数。"""
        with self._lock:
            return self._fetch_count

    @property
    def is_fresh(self) -> bool:
        """内存缓存是否存在且未过期。"""
        with self._lock:
            if self._payload is None:
                return False
            return (time.time() - self._fetched_at) <= self._ttl

    def update_payload_inplace(self, mutator) -> None:
        """在锁内对缓存 payload 执行原地修改。

        用于 pick_and_train 的训练循环中：训练成功后需要扣减本地缓存的
        资源和技能等级，但不发送新的 Index 请求。

        Args:
            mutator: 接受 payload dict 的回调函数。
        """
        with self._lock:
            if self._payload is not None:
                mutator(self._payload)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _do_fetch(
        self,
        reason: str,
        client: Any = None,
        update_shared: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """发送 Index/index 网络请求并更新缓存。

        必须在 self._lock 内调用。
        """
        use_client = client or self._client
        if use_client is None:
            self._log(f"请求失败：无可用 client ({reason})")
            return None

        payload_dict = {"time": int(time.time()), "furniture_data": False}
        self._log(f"发送 Index/index 请求 ({reason})")

        try:
            resp = use_client.send_request(API_INDEX_INDEX, payload_dict)
        except Exception as exc:
            self._log(f"请求异常：{exc}")
            return None

        if self._is_error(resp):
            self._log(f"请求返回错误：{self._compact_error(resp)}")
            return None

        # 更新内存缓存
        self._payload = resp
        self._fetched_at = time.time()
        self._source = f"network:{reason}"
        self._fetch_count += 1

        # 更新共享文件缓存（可选）
        if update_shared and self._shared_file:
            self._write_shared_cache(resp, reason)

        # 更新妖精缓存（兼容性：所有模块在 Index 请求后都会调用此函数）
        self._update_fairy_cache(resp)

        return resp

    def _read_shared_cache(self) -> Optional[Dict[str, Any]]:
        """读取共享文件缓存，检查 TTL 和服务器匹配。"""
        if not self._shared_file:
            return None
        path = self._root_dir / self._shared_file
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None

        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else None
        if payload is None and isinstance(raw.get("user_info"), dict):
            payload = raw  # 兼容：整个文件就是 payload

        if not isinstance(payload, dict):
            return None

        saved_at = int(raw.get("saved_at") or raw.get("time") or raw.get("created_at") or 0)
        if saved_at <= 0:
            return None
        age = time.time() - saved_at
        if age > self._shared_ttl:
            return None

        return payload

    def _write_shared_cache(self, payload: Dict[str, Any], reason: str) -> None:
        """写入共享文件缓存。"""
        if not self._shared_file:
            return
        path = self._root_dir / self._shared_file
        try:
            data = {
                "schema": "gfam_index_cache_v1",
                "source": f"{self._label}:{reason}",
                "saved_at": int(time.time()),
                "payload": payload,
            }
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            self._log(f"写入共享缓存失败：{exc}")

    def _update_fairy_cache(self, payload: Dict[str, Any]) -> None:
        """调用 gfam_fairy_stats 的妖精缓存更新（兼容性）。"""
        try:
            from gfam_fairy_stats import update_fairy_cache_from_index_payload
            update_fairy_cache_from_index_payload(
                payload, source=f"{self._label} Index/index"
            )
        except Exception:
            pass  # fairy_stats 不在所有环境中可用

    @staticmethod
    def _is_error(resp: Any) -> bool:
        """判断响应是否为错误（与各模块的 check_step_error 逻辑一致）。"""
        if resp is None:
            return True
        if not isinstance(resp, dict):
            return True
        if resp.get("error") or resp.get("error_local"):
            return True
        return False

    @staticmethod
    def _compact_error(resp: Any) -> str:
        """提取错误信息的简短摘要。"""
        if not isinstance(resp, dict):
            return str(resp)[:200]
        err = resp.get("error") or resp.get("error_local") or "unknown"
        return str(err)[:200]

    def _log(self, message: str) -> None:
        """输出带标签的日志（使用 print，与各模块风格一致）。"""
        print(f"[{self._label}] {message}")


# ---------------------------------------------------------------------------
# 模块级工厂函数：快速创建预配置的 IndexCacheManager
# ---------------------------------------------------------------------------

def create_epa_cache_manager(client: Any, root_dir: Path) -> IndexCacheManager:
    """为 EPA / 13-4 / Smart EPA 模块创建缓存管理器。

    TTL = 60 秒（覆盖 -a → -r 的典型间隔）。
    启用共享文件缓存（与 factory 模块互通）。
    """
    return IndexCacheManager(
        client,
        ttl=60,
        label="EPA",
        shared_file=SHARED_INDEX_FILE,
        root_dir=root_dir,
    )


def create_pick_cache_manager(client: Any, root_dir: Path) -> IndexCacheManager:
    """为 Pick & Train 模块创建缓存管理器。

    TTL = 30 秒（资料币变化较快，缓存窗口更短）。
    不启用共享文件缓存（pick 的 Index 数据对 factory 无意义）。
    """
    return IndexCacheManager(
        client,
        ttl=30,
        label="Pick",
        shared_file=None,
        root_dir=root_dir,
    )
