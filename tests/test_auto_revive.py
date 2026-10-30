"""Compile real PlayerBots resurrection code with a controlled clock and party."""
import argparse
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_gear_generation import extract


PREFIX = r'''
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
using uint32 = uint32_t;
using time_t = int64_t;
time_t mockNow = 1000;
#define time(...) mockNow
constexpr uint32 PLAYER_FLAGS = 0, PLAYER_FLAGS_GHOST = 1, PLAYER_SELF_RES_SPELL = 2;
constexpr uint32 TELE_TO_FORCE_MAP_CHANGE = 16;
constexpr uint32 DUNGEON_MAP = 33, WORLD_MAP = 0, BATTLEGROUND_MAP = 489;
enum class BotState { BOT_STATE_DEAD, BOT_STATE_COMBAT, BOT_STATE_NON_COMBAT };
struct MapEntry {
    bool dungeon = false;
    bool IsDungeon() const { return dungeon; }
};
struct MapStore {
    std::map<uint32, MapEntry> entries{{DUNGEON_MAP, {true}}, {WORLD_MAP, {false}}, {BATTLEGROUND_MAP, {false}}};
    template<class T> T const* LookupEntry(uint32 id) const {
        auto it = entries.find(id); return it == entries.end() ? nullptr : &it->second;
    }
} sMapStorage;
struct Map {
    uint32 id = 0;
    bool IsDungeon() const { return sMapStorage.LookupEntry<MapEntry>(id)->IsDungeon(); }
};
struct Corpse {
    uint32 map = DUNGEON_MAP, instance = 7;
    uint32 GetMapId() const { return map; }
    uint32 GetInstanceId() const { return instance; }
};
struct PlayerbotAI;
struct Group;
struct Player {
    bool alive = true, world = true, combat = false, teleport = false, ghost = false;
    bool bg = false, hardcore = false, teleportFails = false;
    uint32 map = DUNGEON_MAP, instance = 7, selfRez = 0, bones = 0, teleports = 0, options = 0;
    uint32 pendingMap = 0; float x = 1, pendingX = 0;
    Map mapObj;
    Group* group = nullptr; PlayerbotAI* ai = nullptr; Corpse* corpse = nullptr;
    std::set<uint32> spells;
    bool IsAlive() const { return alive; }
    bool IsInWorld() const { return world; }
    bool IsInCombat() const { return combat; }
    bool IsBeingTeleported() const { return teleport; }
    bool InBattleGround() const { return bg; }
    uint32 GetMapId() const { return map; }
    uint32 GetInstanceId() const { return instance; }
    Map* FindMap() { mapObj.id = map; return world ? &mapObj : nullptr; }
    Corpse* GetCorpse() const { return corpse; }
    Group* GetGroup() const { return group; }
    bool IsInGroup(Player* other) const { return group && group == other->group; }
    bool HasSpell(uint32 spell) const { return spells.count(spell); }
    bool HasFlag(uint32, uint32) const { return ghost; }
    uint32 GetUInt32Value(uint32) const { return selfRez; }
    float GetPositionX() const { return x; }
    float GetPositionY() const { return 2; }
    float GetPositionZ() const { return 3; }
    float GetOrientation() const { return 4; }
    float GetDistance(Player* other) const {
        return map == other->map && instance == other->instance ? std::fabs(x - other->x) : 1e9f;
    }
    char const* GetName() const { return "fixture"; }
    void ResurrectPlayer(float) { if (!hardcore) { alive = true; ghost = false; } }
    void SpawnCorpseBones() { ++bones; corpse = nullptr; }
    // Asynchronous like the core: only the teleport ack (land) moves the player.
    bool TeleportTo(uint32 mapId, float px, float, float, float, uint32 flags) {
        if (teleportFails) return false;
        ++teleports; options = flags; teleport = true; pendingMap = mapId; pendingX = px; return true;
    }
    void land(Player const& owner, bool arrive = true) {
        teleport = false; map = pendingMap; instance = owner.instance; if (arrive) x = pendingX;
    }
};
struct GroupReference {
    Player* player; GroupReference* following = nullptr;
    Player* getSource() const { return player; }
    GroupReference* next() const { return following; }
};
struct Group {
    GroupReference* first;
    GroupReference* GetFirstMember() const { return first; }
};
struct PlayerbotAI {
    Player* master; Player* bot; BotState state = BotState::BOT_STATE_DEAD;
    uint32 resets = 0; bool staleMovement = true;
    bool HasRealPlayerMaster() const { return master != nullptr; }
    Player* GetMaster() const { return master; }
    bool IsStateActive(BotState value) const { return state == value; }
    bool HasStrategy(char const*, BotState) const { return true; }
    void StopMoving() {}
    void ChangeEngine(BotState value) { state = value; }
    void Reset(bool full) { if (full) { ++resets; staleMovement = false; } }
    void OnResurrected();
    void TellPlayerNoFacing(Player*, char const*) {}
};
PlayerbotAI* GetBotAI(Player* player) { return player->ai; }
struct Config { bool autoReviveWithoutRezzer = true, windrunnerCompanionMode = true; uint32 autoReviveDelay = 5; }
    sPlayerbotAIConfig;
struct Facade {
    bool UnitIsDead(Player* player) const { return !player->alive; }
    bool IsAlive(Player* player) const { return player->alive; }
} sServerFacade;
struct Logger {
    template<class... Args> void outDetail(Args...) {}
    template<class... Args> void outError(Args...) {}
} sLog;
struct Event {};
struct AutoReviveAction {
    PlayerbotAI* ai; Player* bot; time_t quietSince = 0; uint32 teleports = 0;
    Player* GetMaster() const { return ai->master; }
    static bool CanResurrectOthers(Player*);
    static bool IsDungeonDeath(Player*);
    static bool ShouldWaitForAutoRevive(Player*);
    static bool HasLivingRezzer(Player*);
    static bool WillAutoRevive(Player*);
    void ResetState();
    bool isUseful();
    bool Execute(Event&);
};
void check(bool ok, char const* message) { if (!ok) throw std::runtime_error(message); }
'''

CHECKS = r'''
int main() {
    try {
        Player owner, bot, other;
        bot.alive = false;
        PlayerbotAI ai{&owner, &bot}; bot.ai = &ai;
        GroupReference r3{&other}, r2{&bot, &r3}, r1{&owner, &r2}; Group group{&r1};
        owner.group = bot.group = other.group = &group;
        AutoReviveAction action{&ai, &bot}; Event event;
        auto kill = [&]() { bot.alive = false; ai.state = BotState::BOT_STATE_DEAD; };

        // Dungeon, nobody can rez: up after the delay (30s floor in companion mode).
        check(AutoReviveAction::IsDungeonDeath(&bot), "Dungeon map not recognised");
        check(AutoReviveAction::ShouldWaitForAutoRevive(&bot), "Dungeon release/corpse run not suppressed");
        owner.alive = false;
        check(!AutoReviveAction::ShouldWaitForAutoRevive(&owner), "Human player treated as a companion");
        owner.alive = true;
        check(!action.isUseful(), "Timer must begin before resurrection");
        mockNow = 1005; check(!action.isUseful(), "Old five-second setting bypassed minimum");
        mockNow = 1029; check(!action.isUseful(), "Revived before thirty seconds");
        mockNow = 1030; check(action.isUseful(), "Thirty-second boundary excluded");
        other.map = 0; other.instance = 0; other.alive = false; other.combat = true;
        check(!action.Execute(event) && !bot.alive, "Queued revive ignored distant/dead member in combat");
        other.combat = false; mockNow = 1040; check(!action.isUseful(), "Quiet period was not restarted");
        mockNow = 1069; check(!action.isUseful(), "Re-entering combat did not reset timer");
        mockNow = 1070; check(action.Execute(event), "Revive failed after full quiet period");
        check(bot.alive && bot.bones == 1 && ai.state == BotState::BOT_STATE_NON_COMBAT &&
              ai.resets == 1 && !ai.staleMovement, "Resurrection left stale dead AI/movement state");
        check(!action.Execute(event) && bot.bones == 1, "Living bot resurrected twice");

        // Dungeon with a living rezzer: it gets the first chance, auto revive
        // is the fallback after twice the delay.
        kill(); other.alive = true; other.map = DUNGEON_MAP; other.instance = 7; other.spells.insert(2006);
        check(AutoReviveAction::WillAutoRevive(&bot), "Dungeon rezzer cancelled the fallback");
        mockNow = 2000; check(!action.isUseful(), "Rezzer timer must begin first");
        mockNow = 2030; check(!action.isUseful() && !action.Execute(event) && !bot.alive,
                              "Revived at the single delay although a rezzer was alive");
        mockNow = 2059; check(!action.isUseful(), "Revived before twice the delay");
        mockNow = 2060; check(action.Execute(event) && bot.alive, "Rezzer fallback did not fire after twice the delay");
        kill(); other.instance = 8;
        check(!AutoReviveAction::HasLivingRezzer(&bot), "Rezzer in another instance counted");
        other.instance = 7; other.spells.clear();

        // Away from the master: move first, resurrect on a later tick.
        bot.x = 100;
        mockNow = 3000; action.isUseful(); mockNow = 3030;
        uint32 teleports = bot.teleports;
        check(action.Execute(event) && bot.teleports == teleports + 1 && bot.teleport && !bot.alive,
              "Resurrected before the move to the master completed");
        mockNow = 3031; check(!action.isUseful() && !action.Execute(event) && !bot.alive, "Revived mid-teleport");
        check(action.quietSince == 3000, "Teleport in flight restarted the quiet period");
        bot.land(owner);
        check(action.isUseful(), "Quiet period lost across the teleport");
        check(action.Execute(event) && bot.alive && bot.teleports == teleports + 1 && bot.x == owner.x,
              "Not raised next to the master after landing");

        // A refused teleport falls back to resurrecting in place.
        kill(); bot.x = 100; bot.teleportFails = true;
        mockNow = 4000; action.isUseful(); mockNow = 4030;
        check(action.Execute(event) && bot.alive, "Refused teleport left the bot dead");
        bot.teleportFails = false;

        // Teleports that never land next to the master are bounded.
        kill(); bot.x = 100; teleports = bot.teleports;
        mockNow = 5000; action.isUseful(); mockNow = 5030;
        for (int i = 0; i < 3; ++i) {
            check(action.Execute(event) && !bot.alive, "Bot raised before its teleport tries ran out");
            bot.land(owner, false);
        }
        check(action.Execute(event) && bot.alive && bot.teleports == teleports + 4,
              "Endless teleport loop / no in-place fallback");
        bot.land(owner);

        // Released ghost outside, corpse in the dungeon: into the instance first.
        Corpse corpse; kill(); bot.ghost = true; bot.corpse = &corpse;
        bot.map = WORLD_MAP; bot.instance = 2; bot.x = 500;
        check(AutoReviveAction::ShouldWaitForAutoRevive(&bot), "Ghost of a dungeon death allowed to corpse-run");
        mockNow = 6000; check(!action.isUseful(), "Released ghost skipped delay");
        mockNow = 6030; check(action.Execute(event) && !bot.alive && bot.options == 0,
                              "Outdoor ghost not moved into the dungeon first");
        bot.land(owner); check(action.Execute(event) && bot.alive && bot.map == DUNGEON_MAP,
                               "Outdoor ghost could not recover to dungeon owner");
        corpse = Corpse(); kill(); bot.ghost = true; bot.corpse = &corpse; bot.instance = 8;
        mockNow = 7000; action.isUseful(); mockNow = 7030;
        check(action.Execute(event) && bot.options == TELE_TO_FORCE_MAP_CHANGE,
              "Same-map recovery stayed in wrong instance");
        bot.land(owner); check(action.Execute(event) && bot.alive, "Wrong-instance ghost not raised after landing");

        corpse = Corpse(); kill(); bot.ghost = true; bot.corpse = &corpse; corpse.instance = 9; bot.map = WORLD_MAP;
        check(!AutoReviveAction::WillAutoRevive(&bot), "Unrelated dungeon corpse admitted");
        corpse.instance = 7; bot.map = DUNGEON_MAP; bot.instance = 7; bot.ghost = false; bot.corpse = nullptr;
        owner.alive = false;
        check(!AutoReviveAction::WillAutoRevive(&bot) && AutoReviveAction::ShouldWaitForAutoRevive(&bot),
              "Dead master: must wait (never release) without reviving");
        owner.alive = true;

        // Open world: corpse runs are not suppressed, a rezzer blocks auto
        // revive, and without one the bot gets up in place.
        owner.map = bot.map = other.map = WORLD_MAP; owner.instance = bot.instance = other.instance = 0;
        check(!AutoReviveAction::IsDungeonDeath(&bot) && !AutoReviveAction::ShouldWaitForAutoRevive(&bot),
              "Open-world corpse run suppressed");
        other.spells.insert(2006);
        check(!AutoReviveAction::WillAutoRevive(&bot), "Open-world rezzer was ignored");
        other.spells.clear(); bot.x = 100; teleports = bot.teleports;
        mockNow = 8000; action.isUseful(); mockNow = 8030;
        check(action.Execute(event) && bot.alive && bot.teleports == teleports,
              "Open-world revive moved the unreleased bot");
        Corpse worldCorpse; worldCorpse.map = WORLD_MAP; worldCorpse.instance = 0;
        kill(); bot.ghost = true; bot.corpse = &worldCorpse;
        mockNow = 9000; action.isUseful(); mockNow = 9030;
        check(action.Execute(event) && bot.alive && bot.teleports == teleports + 1,
              "Open-world ghost did not rejoin owner after reviving");
        bot.land(owner);
        owner.map = bot.map = other.map = BATTLEGROUND_MAP; kill(); bot.bg = true;
        check(!AutoReviveAction::ShouldWaitForAutoRevive(&bot), "Battleground treated as a dungeon");
        bot.bg = false; owner.map = bot.map = other.map = DUNGEON_MAP; owner.instance = bot.instance = other.instance = 7;

        bot.selfRez = 1;
        check(!action.isUseful(), "Soulstone priority was lost");
        bot.selfRez = 0; bot.hardcore = true;
        mockNow = 10000; action.isUseful(); mockNow = 10030;
        uint32 bones = bot.bones;
        check(!action.Execute(event) && bot.bones == bones, "Hardcore corpse was destroyed after refused resurrection");
        std::cout << "PASS: dungeon-only waiting, rezzer fallback at twice the delay, teleport before resurrect, "
                     "teleport failure/loop guards, open-world behaviour, AI reset, ghost/instance recovery\n";
    } catch (std::exception const& error) {
        std::cerr << "FAIL: " << error.what() << '\n'; return 1;
    }
}
'''


def run(server):
    bots = server / "src/modules/PlayerBots/playerbot"
    cpp = (bots / "strategy/actions/AutoReviveAction.cpp").read_text(encoding="utf-8")
    ai = (bots / "PlayerbotAI.cpp").read_text(encoding="utf-8")
    source = PREFIX + extract(cpp, "const uint32 REZ_SPELLS[] =", ";")
    source += "".join(line + "\n" for line in
                      re.findall(r"^\s*const (?:uint32|float) [A-Z_]+ = [^;{]+;", cpp, re.M))
    source += extract(ai, "void PlayerbotAI::OnResurrected()")
    for signature in ("bool AutoReviveAction::CanResurrectOthers(", "bool AutoReviveAction::IsDungeonDeath(",
                      "bool AutoReviveAction::ShouldWaitForAutoRevive(", "bool AutoReviveAction::HasLivingRezzer(",
                      "bool AutoReviveAction::WillAutoRevive(", "void AutoReviveAction::ResetState()",
                      "bool AutoReviveAction::isUseful()", "bool AutoReviveAction::Execute("):
        source += extract(cpp, signature)
    source += CHECKS
    compile_and_run(source)


def compile_and_run(source):
    with tempfile.TemporaryDirectory(prefix="companion-revive-test-") as directory:
        work = Path(directory)
        (work / "checks.cpp").write_text(source, encoding="utf-8")
        if os.name == "nt":
            vswhere = Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
            install = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip()
            vcvars = Path(install) / "VC/Auxiliary/Build/vcvars64.bat"
            script = work / "build.cmd"
            script.write_text(f'@echo off\ncall "{vcvars}" >nul\nif errorlevel 1 exit /b 1\n'
                              'cl /nologo /EHsc /std:c++17 /W3 checks.cpp /Fe:checks.exe\n')
            command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(script)]
        else:
            command = [shutil.which("c++") or "c++", "-std=c++17", "checks.cpp", "-o", "checks.exe"]
        subprocess.run(command, cwd=work, check=True)
        subprocess.run([str(work / "checks.exe")], cwd=work, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path, default=Path(__file__).resolve().parents[3])
    run(parser.parse_args().server)
