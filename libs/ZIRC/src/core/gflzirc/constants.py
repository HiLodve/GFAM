# ===== Server URLs based on server name =====
SERVERS = {
    "M4A1": "http://gfcn-game.gw.merge.sunborngame.com/index.php/1000",
    "AR15": "http://gfcn-game.bili.merge.sunborngame.com/index.php/5000",
    "SOP": "http://gfcn-game.ios.merge.sunborngame.com/index.php/3000",
    "RO635": "http://gfcn-game.ly.merge.sunborngame.com/index.php/4000",
    "M16": "http://gfcn-game.tx.sunborngame.com/index.php/2000",
    "EN": "http://gf-game.sunborngame.com/index.php/1001",
}

# ===== Crypto Keys =====
STATIC_KEY = "yundoudou"
DEFAULT_SIGN = "1234567890abcdefghijklmnopqrstuv"

# ===== API Endpoints =====

# Target
API_TARGET_TRAIN_ADD = "Targettrain/addCollect"
# Mission
API_MISSION_COMBINFO = "Mission/combinationInfo"
API_MISSION_START = "Mission/startMission"
API_MISSION_ABORT = "Mission/abortMission"
API_MISSION_END_TURN = "Mission/endTurn"
API_MISSION_START_ENEMY_TURN = "Mission/startEnemyTurn"
API_MISSION_END_ENEMY_TURN = "Mission/endEnemyTurn"
API_MISSION_START_TURN = "Mission/startTurn"
API_MISSION_TEAM_MOVE = "Mission/teamMove"
API_MISSION_ALLY_MYSIDE_MOVE = "Mission/allyMySideMove"
API_MISSION_SUPPLY = "Mission/supplyTeam"
API_MISSION_BATTLE_FINISH = "Mission/battleFinish"
API_MISSION_BUILDING_SKILL_PERFORM_ON_DEATH = "Mission/buildingSkillPerformOnDeath"
# Index
API_INDEX_INDEX = "Index/index"
API_INDEX_GUIDE = "Index/guide"
# Gun
API_GUN_RETIRE = "Gun/retireGun"
# Daily
API_DAILY_RESET_MAP = "Daily/resetMap"

#=====  Common Mission Guide Courses =====

GUIDE_COURSE_11880 = [
    1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,1,1,1,1,
    0,1,0,0,0,0,0,0,1,1,1,1,1,1,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
    1,1,1,1,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,1,0,0,0,0,0,0,1,1,1,
    0,0,1,0,1,1,1,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
    1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,1,1,1,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,
    1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,1,1,1,0,0,
    1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1
]

GUIDE_COURSE_10352 = [
    1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
    1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
    1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
    1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
    1,1,1,1,1,1,1,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
    1,1,1,1,1,1,1,1,1,0,1,1,1,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
    1,1,1,1
]