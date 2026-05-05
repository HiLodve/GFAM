#!/usr/bin/env node
/* 少女全自动 / Girl Fully Automatic (GFAM) */
const readline = require('readline');
const path = require('path');
const fs = require('fs');

const PROJECT_NAME = '少女全自动 / Girl Fully Automatic (GFAM)';
const ROOT = __dirname;
const MODULE_DIR = path.join(ROOT, 'modules');
const GFLZIRC_INIT = path.join(ROOT, 'libs', 'ZIRC', 'src', 'core', 'gflzirc', '__init__.py');
const STATE_FILE = path.join(ROOT, '.gfam_state.json');
const AUTH_FILE = path.join(ROOT, '.gfam_auth.json');

let currentServer = 'SOP';
let rl = null;

const modules = [
  { id: 'epa_plus', aliases: ['epa', 'epa_plus', 'epaplus', '打捞', 'epa打捞'], title: 'epa_plus：EPA 打捞', menuTitle: 'epa_plus（EPA 打捞）', file: 'epa_plus.py', hiddenOnServers: ['EN'] },
  { id: '13-4', aliases: ['134', '13-4', '13_4', '13.4', 'train134', 'resource134', '13-4练级', '13-4资源', '13-4打捞'], title: '13-4：五战练级 / 四项基础资源打捞', menuTitle: '13-4（五战练级 / 四项基础资源打捞）', file: 'gfam_13_4.py', hiddenOnServers: [] },
  { id: 'a10-resource', aliases: ['a10-resource', 'a10res', 'a10资源', 'a10四项', '普通a10资源', '四项资源a10', '思想资源', '四项资源获取'], title: 'A-10：四项资源获取', menuTitle: 'A-10（单人不移动四项资源获取）', file: 'gfam_a10_resource.py', hiddenOnServers: ['EN'] },
  { id: 'pick', aliases: ['pick', 'train', 'picktrain', 'pick_and_train', '资料', '自动训练'], title: 'pick_and_train：获取训练资料 / 自动训练 / 自动循环', menuTitle: 'pick_and_train（获取训练资料 / 自动训练 / 自动循环）', file: 'pick_and_train.py', hiddenOnServers: [] },
  { id: 'f2p', aliases: ['f2p', '10', '零元购'], title: '零元购 f2p', menuTitle: '零元购 f2p', file: 'f2p.py', hiddenOnServers: [] },
  { id: 'f2p_pr', aliases: ['f2p_pr', 'f2ppr', 'pr', '11', '零元购pr', '零元购_pr'], title: '零元购 PR（额外核心）', menuTitle: '零元购 PR（额外核心）', file: 'f2p_pr.py', hiddenOnServers: [] },
  { id: 'smart', aliases: ['smart', 'coach', '9', '教练', '妙妙小巧思', '教练の妙妙小巧思', '一键', '一键打捞', '一键计划', '装备一键', '装备一键打捞', '夜战装备一键打捞'], title: '教练の妙妙小巧思（一键打捞计划/装备一键打捞）', menuTitle: '教练の妙妙小巧思（一键打捞计划/装备一键打捞）', file: 'gfam_smart_epa.py', hiddenOnServers: ['EN'] },
  { id: 'greyzone', aliases: ['greyzone', 'gz', 'halloween', 'grey', '灰域', '彩蛋', '灰域彩蛋', '灰域自动彩蛋'], title: '灰域自动彩蛋', menuTitle: '灰域自动彩蛋', file: 'gfam_greyzone_halloween.py', hiddenOnServers: ['EN'] }
];

function readJson(file, fallback) { try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return fallback; } }
function writeJson(file, data) { fs.writeFileSync(file, JSON.stringify(data, null, 2), { encoding: 'utf8' }); }
function normalizeServer(input) {
  const cmd = String(input || '').trim().toUpperCase().replace('_', '-');
  if (!cmd) return currentServer || 'SOP';
  if (['1', '-1', 'SOP'].includes(cmd)) return 'SOP';
  if (['2', '-2', 'RO635', 'RO'].includes(cmd)) return 'RO635';
  if (['3', '-3', 'M4A1', 'M4'].includes(cmd)) return 'M4A1';
  if (['4', '-4', 'M16'].includes(cmd)) return 'M16';
  if (['5', '-5', 'AR-15', 'AR15'].includes(cmd)) return 'AR-15';
  if (['6', '-6', 'EN', 'GLOBAL'].includes(cmd)) return 'EN';
  return null;
}
function loadState() { const s = readJson(STATE_FILE, {}); if (s.server) currentServer = normalizeServer(s.server) || 'SOP'; }
function saveState() { const old = readJson(STATE_FILE, {}); writeJson(STATE_FILE, { ...old, server: currentServer, updated_at: new Date().toISOString() }); }
function getFairyAutoEnabled() { const st = readJson(STATE_FILE, {}); return st.fairy_auto_enabled === true; }
function setFairyAutoEnabled(v) { const st = readJson(STATE_FILE, {}); st.server = currentServer; st.fairy_auto_enabled = !!v; st.updated_at = new Date().toISOString(); writeJson(STATE_FILE, st); }
function toggleFairyAuto() { const next = !getFairyAutoEnabled(); setFairyAutoEnabled(next); console.log(next ? '[+] 已开启：妖精自动建造 / 自动强化。' : '[*] 已关闭：妖精自动建造 / 自动强化。'); }
function checkGflzircReady() {
  if (fs.existsSync(GFLZIRC_INIT)) { console.log('[+] 已检测到内置 gflzirc：libs/ZIRC/src/core/gflzirc'); return true; }
  console.log('[!] 未检测到内置 gflzirc：libs/ZIRC/src/core/gflzirc/__init__.py');
  console.log('[!] 请重新完整解压压缩包。');
  return false;
}
function isHidden(item) { return (item.hiddenOnServers || []).includes(currentServer); }
function visibleModules() { return modules.filter(item => !isHidden(item)); }
function hiddenModules() { return modules.filter(item => isHidden(item)); }
function getAuth() {
  const a = readJson(AUTH_FILE, null);
  if (!a) return null;
  if (String(a.server || '').toUpperCase() !== currentServer) return null;
  if (!a.uid || !a.sign) return null;
  return a;
}
function clearAuth(reason) {
  try {
    if (fs.existsSync(AUTH_FILE)) fs.unlinkSync(AUTH_FILE);
  } catch (e) {
    // 忽略清理失败，避免影响退出流程。
  }
  try {
    const st = readJson(STATE_FILE, {});
    if (st && st.auth) delete st.auth;
    st.updated_at = new Date().toISOString();
    writeJson(STATE_FILE, st);
  } catch (e) {}
  if (reason) console.log(reason);
}
function exitCleanly() {
  clearAuth('[*] 已清除本地 UID/SIGN，下次启动将重新获取。');
  console.log('[*] 已退出少女全自动（GFAM）。');
  closeReadline();
}
process.on('SIGINT', () => {
  clearAuth('\n[*] 检测到中断，已清除本地 UID/SIGN。');
  process.exit(0);
});
process.on('SIGTERM', () => {
  clearAuth();
  process.exit(0);
});
process.on('SIGHUP', () => {
  clearAuth();
  process.exit(0);
});
function printServerMenu() {
  console.log(`\n================ ${PROJECT_NAME} 服务器选择 ================`);
  console.log('  1 / SOP   : SOP');
  console.log('  2 / RO635 : RO635');
  console.log('  3 / M4A1  : M4A1');
  console.log('  4 / M16   : M16');
  console.log('  5 / AR-15 : AR-15');
  console.log('  6 / EN    : EN');
  console.log('------------------------------------------------');
  console.log('提示：可输入编号或服务器名，直接回车保持当前服务器。');
  console.log('================================================\n');
}
function printMenu() {
  const auth = getAuth();
  console.log(`\n================ ${PROJECT_NAME} ================`);
  console.log(`当前服务器：${currentServer}`);
  if (auth) console.log(`UID/SIGN：已获取（UID ${String(auth.uid).slice(0, -3)}***）`);
  console.log('------------------------------------------------');
  visibleModules().forEach((item, idx) => {
    const aliasHint = item.id === '13-4' ? '13-4' : item.aliases[0];
    console.log(`  ${idx + 1} / ${aliasHint.padEnd(8)} : ${item.menuTitle}`);
  });
  console.log(`  fairy        : 妖精自动建造 / 自动强化：${getFairyAutoEnabled() ? '开启' : '关闭'}`);
  console.log('  auth         : 重新获取 UID/SIGN');
  console.log('  server       : 切换服务器');
  console.log('  0 / exit     : 退出');
  console.log('------------------------------------------------');
  console.log('提示：选择服务器后会先统一获取 UID/SIGN，再进入功能模块。');
  console.log('提示：进入某个模块后，该模块会接管命令行；模块退出后会回到 GFAM 菜单。');
  console.log('提示：开启 fairy 后，功能模块运行期间会后台执行妖精建造/强化循环。');
  console.log('================================================\n');
}
function resolveChoice(input) {
  const cmd = String(input || '').trim().toLowerCase();
  if (!cmd) return null;
  if (['0', 'e', '-e', 'exit', 'quit', 'q', '退出'].includes(cmd)) return 'exit';
  if (['server', '-server', '服', '服务器', '切换服务器'].includes(cmd)) return 'server';
  if (['auth', '-auth', 'login', '登录', '重新登录', '抓取', 'uid', 'sign'].includes(cmd)) return 'auth';
  if (['fairy', '-fairy', '妖精', '妖精自动', '妖精建造', '妖精强化'].includes(cmd)) return 'fairy';
  const visible = visibleModules();
  const n = Number.parseInt(cmd, 10);
  if (String(n) === cmd && n >= 1 && n <= visible.length) return visible[n - 1];
  for (const item of visible) if (cmd === item.id.toLowerCase() || item.aliases.map(x => String(x).toLowerCase()).includes(cmd)) return item;
  for (const item of hiddenModules()) if (cmd === item.id.toLowerCase() || item.aliases.map(x => String(x).toLowerCase()).includes(cmd)) return { hidden: true, item };
  return null;
}
function openReadline() { if (!rl) rl = readline.createInterface({ input: process.stdin, output: process.stdout }); return rl; }
function closeReadline() { if (rl) { rl.close(); rl = null; } }
function ask(question, cb) { openReadline().question(question, cb); }
function escapeCmdValue(value) { return String(value || '').replace(/\^/g, '^^').replace(/&/g, '^&').replace(/\|/g, '^|').replace(/</g, '^<').replace(/>/g, '^>').replace(/"/g, ''); }
function writeNext(lines) { fs.writeFileSync(path.join(ROOT, '.gfam_next_module.cmd'), lines.join('\r\n') + '\r\n', { encoding: 'utf8' }); }
function requestAuthCapture() {
  saveState();
  const script = path.join(MODULE_DIR, 'gfam_auth_capture.py');
  if (!fs.existsSync(script)) { console.log(`[!] 授权模块不存在：${script}`); return; }
  writeNext([
    '@echo off',
    'set "GFAM_MODULE_FILE=gfam_auth_capture.py"',
    'set "GFAM_MODULE_TITLE=获取 UID/SIGN"',
    `set "GFAM_SELECTED_SERVER=${escapeCmdValue(currentServer)}"`,
    `set "GFAM_SERVER=${escapeCmdValue(currentServer)}"`,
    'set "GFAM_SKIP_SERVER_MENU=1"',
    'set "GFAM_AUTH_CAPTURE=1"'
  ]);
  console.log(`\n[*] 当前服务器：${currentServer}`);
  console.log('[*] 即将先获取 UID/SIGN。');
  console.log('[*] 请按提示登录游戏，进入指挥官主界面后会返回 GFAM 菜单。');
  closeReadline();
  process.exit(77);
}
function ensureAuthThen(cb) {
  if (getAuth()) { cb(); return; }
  console.log('\n[!] 当前服务器尚未获取 UID/SIGN。');
  console.log('[!] 需要先完成一次登录抓取，然后才能选择功能模块。');
  requestAuthCapture();
}
function runModule(item) {
  const script = path.join(MODULE_DIR, item.file);
  if (!fs.existsSync(script)) { console.log(`[!] 模块文件不存在：${script}`); return; }
  const auth = getAuth();
  const lines = [
    '@echo off',
    `set "GFAM_MODULE_FILE=${escapeCmdValue(item.file)}"`,
    `set "GFAM_MODULE_TITLE=${escapeCmdValue(item.title)}"`,
    `set "GFAM_SELECTED_SERVER=${escapeCmdValue(currentServer)}"`,
    `set "GFAM_SERVER=${escapeCmdValue(currentServer)}"`,
    'set "GFAM_SKIP_SERVER_MENU=1"',
    'set "GFAM_AUTH_CAPTURE=0"'
  ];
  if (getFairyAutoEnabled()) {
    lines.push('set "GFAM_FAIRY_AUTO_ENABLED=1"');
  } else {
    lines.push('set "GFAM_FAIRY_AUTO_ENABLED=0"');
  }
  if (auth) {
    lines.push(`set "GFAM_USER_UID=${escapeCmdValue(auth.uid)}"`);
    lines.push(`set "GFAM_SIGN_KEY=${escapeCmdValue(auth.sign)}"`);
    lines.push('set "GFAM_AUTH_READY=1"');
  }
  writeNext(lines);
  console.log(`\n[*] 即将启动：${item.title}`);
  console.log(`[*] 当前服务器：${currentServer}`);
  console.log(`[*] 模块文件：${path.relative(ROOT, script)}`);
  console.log('[*] 模块会直接接管命令行输入。');
  closeReadline();
  process.exit(77);
}
function askServer(cb) {
  printServerMenu();
  ask(`GFAM(服务器, 当前${currentServer})> `, (answer) => {
    const s = normalizeServer(answer);
    if (!s) { console.log('[!] 未识别服务器，请输入 SOP / RO635 / M4A1 / M16 / AR-15 / EN。'); askServer(cb); return; }
    currentServer = s;
    saveState();
    console.log(`[+] 已选择服务器：${currentServer}`);
    cb();
  });
}
function loop() {
  ensureAuthThen(() => {
    printMenu();
    ask(`GFAM[${currentServer}]> `, (answer) => {
      const choice = resolveChoice(answer);
      if (choice === 'exit') { exitCleanly(); return; }
      if (choice === 'server') { askServer(loop); return; }
      if (choice === 'auth') { requestAuthCapture(); return; }
      if (choice === 'fairy') { toggleFairyAuto(); loop(); return; }
      if (choice && choice.hidden) { console.log(`[!] ${choice.item.menuTitle} 当前不可用。`); loop(); return; }
      if (!choice) { console.log('[!] 未识别输入，请重新选择。'); loop(); return; }
      runModule(choice);
    });
  });
}

loadState();
if (!checkGflzircReady()) process.exit(1);
console.log(`\n================ ${PROJECT_NAME} ================`);
console.log('[*] 欢迎使用少女全自动。');

// run_windows.bat 会在本次程序首次进入 main.js 时设置 GFAM_FORCE_SERVER_SELECT=1。
// 这样即使本地已有 UID/SIGN，也会先让用户确认服务器；
// 从授权模块或功能模块返回主菜单时不再重复弹出服务器选择。
if (process.env.GFAM_FORCE_SERVER_SELECT === '1') {
  askServer(loop);
} else if (getAuth()) {
  loop();
} else {
  askServer(loop);
}
