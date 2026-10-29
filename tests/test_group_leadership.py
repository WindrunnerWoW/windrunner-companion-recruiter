"""Compile actual group maintenance and verify ordinary group authority."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_gear_generation import extract


PREFIX = r'''
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
using uint32 = uint32_t;
using uint8 = uint8_t;
struct ObjectGuid {
    uint32 value = 0;
    ObjectGuid(uint32 v = 0) : value(v) {}
    uint32 GetCounter() const { return value; }
    bool IsEmpty() const { return value == 0; }
    bool operator==(ObjectGuid other) const { return value == other.value; }
};
struct Player;
struct Group {
    struct MemberSlot { ObjectGuid guid; };
    uint32 leader = 0, changes = 0;
    bool bg = false, raid = false;
    std::set<uint32> members, assistants;
    bool isBGGroup() const { return bg; }
    bool isRaidGroup() const { return raid; }
    bool IsMember(ObjectGuid guid) const { return members.count(guid.value); }
    bool IsLeader(ObjectGuid guid) const { return leader == guid.value; }
    bool IsAssistant(ObjectGuid guid) const { return assistants.count(guid.value); }
    ObjectGuid GetLeaderGuid() const { return leader; }
    uint32 GetMembersCount() const { return uint32(members.size()); }
    std::vector<MemberSlot> GetMemberSlots() const {
        std::vector<MemberSlot> slots;
        for (uint32 member : members) slots.push_back({member});
        return slots;
    }
    uint32 GetId() const { return 7; }
    bool HandleHardcoreInteraction(Player*) const { return true; }
    void RemoveInvite(Player*) {}
    bool Create(ObjectGuid guid, char const*) { leader = guid.value; members.insert(guid.value); return true; }
    bool AddMember(ObjectGuid guid, char const*);
    void ChangeLeader(ObjectGuid guid) {
        if (!IsMember(guid)) return;
        leader = guid.value; ++changes;
    }
};
struct Player {
    uint32 id; bool bot = false;
    Group* group = nullptr; Group* original = nullptr;
    bool world = true, teleport = false, bg = false;
    enum class HardcoreInteractionResult { Allowed };
    ObjectGuid GetObjectGuid() const { return id; }
    uint32 GetGUIDLow() const { return id; }
    Group* GetGroup() const { return group; }
    Group* GetOriginalGroup() const { return original; }
    Group* GetGroupInvite() const { return nullptr; }
    bool IsInWorld() const { return world; }
    bool IsBeingTeleported() const { return teleport; }
    bool InBattleGround() const { return bg; }
    char const* GetName() const { return "fixture"; }
    bool IsInGroup(Player* other, bool) const { return group && group == other->group; }
    HardcoreInteractionResult HandleHardcoreInteraction(Player*, bool) const {
        return HardcoreInteractionResult::Allowed;
    }
    void RemoveFromGroup() { if (group) group->members.erase(id); group = nullptr; }
};
struct ObjectMgr {
    std::map<uint32, Player*> players;
    Player* GetPlayer(ObjectGuid guid) const {
        auto it = players.find(guid.value); return it == players.end() ? nullptr : it->second;
    }
    void AddGroup(Group*) {}
} sObjectMgr;
bool Group::AddMember(ObjectGuid guid, char const*) {
    members.insert(guid.value);
    if (Player* player = sObjectMgr.GetPlayer(guid)) player->group = this;
    return true;
}
bool GetBotAI(Player* player) { return player && player->bot; }
struct CompanionContract { uint32 ownerGuid = 0; bool suspended = false; };
struct OwnedCompanion { uint32 ownerGuid = 0; bool invited = true; };
std::map<uint32, CompanionContract> gContracts;
std::map<uint32, OwnedCompanion> gOwnedCompanions;
Player* FindCompanionOwner(uint32 ownerGuid) { return sObjectMgr.GetPlayer(ObjectGuid(ownerGuid)); }
namespace ObjectAccessor { Player* FindConnectedPlayer(ObjectGuid guid) { return sObjectMgr.GetPlayer(guid); } }
uint32 dismissed = 0;
void RequestDismiss(uint32) { ++dismissed; }
constexpr uint32 MAX_GROUP_SIZE = 5, MAX_RAID_SIZE = 40;
uint32 warnings = 0;
void NotifyOwnerCannotLeadGroup(Player*, Group*, Player*) { ++warnings; }
struct Logger { template<class... Args> void outError(Args...) {} } sLog;
void check(bool ok, char const* message) { if (!ok) throw std::runtime_error(message); }
'''

CHECKS = r'''
int main() {
    try {
        Player owner{1}, bot{2, true}, human{3};
        sObjectMgr.players = {{1, &owner}, {2, &bot}, {3, &human}};
        gContracts[2] = CompanionContract{1};
        Group group;
        group.members = {1, 2, 3}; group.leader = 2;
        owner.group = bot.group = human.group = &group;
        check(EnsureCompanionInGroup(&owner, &bot), "Existing member rejected");
        check(group.leader == 1 && group.changes == 1, "Companion leader was not replaced by its master");
        EnsureCompanionInGroup(&owner, &bot);
        check(group.changes == 1, "Maintenance changed leadership repeatedly");

        // Master (contract owner) and leader are distinct. The AI follows the
        // group leader while grouped; the master is the fallback and the only
        // command source.
        group.leader = 2;
        check(GetFollowTarget(&owner, &bot) == &bot, "Grouped companion ignored the in-world group leader");
        group.leader = 3;
        check(GetFollowTarget(&owner, &bot) == &human, "Grouped companion did not follow the group leader");
        check(GetFollowTarget(&owner, &bot) != &owner, "Grouped companion followed its master over the leader");
        bot.bg = true;
        check(GetFollowTarget(&owner, &bot) == &owner, "Battleground companion ignored its master");
        bot.bg = false;
        owner.group = nullptr;
        check(GetFollowTarget(&owner, &bot) == &owner, "Ungrouped companion did not follow its master");
        owner.group = &group;

        group.leader = 2; group.raid = true; group.assistants.insert(1);
        EnsureCompanionInGroup(&owner, &bot);
        check(group.leader == 1, "Companion leader kept leadership in a raid");

        sObjectMgr.players.erase(2); group.leader = 2;
        EnsureCompanionInGroup(&owner, &bot);
        check(group.leader == 1, "Offline temporary companion leader was not replaced");
        gContracts.clear(); gOwnedCompanions[2] = OwnedCompanion{1}; group.leader = 2;
        EnsureCompanionInGroup(&owner, &bot);
        check(group.leader == 1, "Offline permanent companion leader was not replaced");
        sObjectMgr.players[2] = &bot;

        group.leader = 3;
        EnsureCompanionInGroup(&owner, &bot);
        check(group.leader == 3, "Human leader was replaced");
        bot.group = nullptr; group.members.erase(2);
        check(EnsureCompanionInGroup(&owner, &bot), "Raid assistant could not add companion");
        check(group.leader == 3 && bot.group == &group, "Joining changed human leadership");
        bot.group = nullptr; group.members.erase(2); group.assistants.clear();
        check(!EnsureCompanionInGroup(&owner, &bot) && warnings == 1,
              "Nonleader recruited into another human's group");

        // The companion leaves a stale group even when the master's current
        // group cannot take it (the master is neither leader nor assistant).
        Group staleGroup;
        staleGroup.members = {2}; staleGroup.leader = 2;
        bot.group = &staleGroup;
        uint32 const warningsBefore = warnings;
        check(!EnsureCompanionInGroup(&owner, &bot) && bot.group == nullptr &&
              warnings == warningsBefore + 1,
              "Stale group kept when the master could not add the companion");
        warnings = warningsBefore;

        group.members.insert(2); bot.group = &group; group.leader = 1;
        group.ChangeLeader(2);
        EnsureCompanionInGroup(&owner, &bot);
        check(group.leader == 1, "Companion could keep leadership over its master");
        group.ChangeLeader(3);
        check(group.leader == 3, "Human transfer failed");

        group.bg = true; group.leader = 2;
        EnsureCompanionInGroup(&owner, &bot);
        check(group.leader == 2, "Battleground leadership was changed");
        group.bg = false; group.members.erase(1);
        bot.group = nullptr; group.members.erase(2); group.leader = 1;
        owner.world = false; owner.teleport = true;
        check(!EnsureCompanionInGroup(&owner, &bot) && !bot.group && warnings == 1,
              "Owner zoning changed membership or reported a leader error");
        owner.world = true; owner.teleport = false; bot.teleport = true;
        check(!EnsureCompanionInGroup(&owner, &bot) && !bot.group && warnings == 1,
              "Bot zoning changed membership or reported a leader error");
        bot.teleport = false;
        check(!EnsureCompanionInGroup(nullptr, &bot), "Missing owner accepted");
        check(!EnsureCompanionInGroup(&owner, nullptr), "Missing bot accepted");

        // Group membership changes must not end a contract. Only a deliberate
        // removal while the owner stays in that group does. Hooks run after
        // the member left, so the fixture group lists the remaining members.
        Group oldGroup;
        oldGroup.members = {2, 3}; oldGroup.leader = 3;
        bot.group = &oldGroup;
        gContracts.clear(); gOwnedCompanions.clear();
        gContracts[2] = CompanionContract{1};
        GroupScriptProbe probe;
        dismissed = 0;
        owner.group = nullptr;
        probe.OnRemoveMember(&oldGroup, ObjectGuid(1), 0);
        check(dismissed == 0 && gContracts.count(2), "Owner leaving another player dismissed a temporary companion");
        oldGroup.members = {3};
        probe.OnRemoveMember(&oldGroup, ObjectGuid(2), 0);
        check(dismissed == 0 && gContracts.count(2), "Companion leaving with its master ended its contract");

        oldGroup.members = {1, 3}; owner.group = &oldGroup;
        probe.OnRemoveMember(&oldGroup, ObjectGuid(2), 0);
        check(dismissed == 1, "Kicked companion kept its contract");

        // Leaving a group of only bots leaves the companions behind with it.
        dismissed = 0;
        Player otherBot{4, true};
        sObjectMgr.players[4] = &otherBot;
        gContracts[5] = CompanionContract{1};
        Group botGroup;
        botGroup.members = {2, 4, 5}; botGroup.leader = 2;
        owner.group = nullptr;
        probe.OnRemoveMember(&botGroup, ObjectGuid(1), 0);
        check(dismissed == 2, "Owner leaving a bot-only group kept its companions");

        dismissed = 0; gContracts.clear();
        gOwnedCompanions[2] = OwnedCompanion{1};
        owner.group = nullptr; oldGroup.members = {2, 3};
        probe.OnRemoveMember(&oldGroup, ObjectGuid(1), 0);
        check(gOwnedCompanions[2].invited, "Owner leaving another player cleared a permanent companion invitation");
        oldGroup.members = {3};
        probe.OnRemoveMember(&oldGroup, ObjectGuid(2), 0);
        check(gOwnedCompanions[2].invited, "Permanent companion leaving with its master lost its invitation");
        oldGroup.members = {1, 3}; owner.group = &oldGroup;
        probe.OnRemoveMember(&oldGroup, ObjectGuid(2), 0);
        check(!gOwnedCompanions[2].invited, "Kicked permanent companion kept its invitation");

        gOwnedCompanions[2].invited = true;
        botGroup.members = {2, 4}; owner.group = nullptr;
        probe.OnRemoveMember(&botGroup, ObjectGuid(1), 0);
        check(!gOwnedCompanions[2].invited, "Owner leaving a bot-only group kept a permanent companion");

        // A two-member group disbands: leaving it or kicking the last companion.
        gOwnedCompanions.clear(); gContracts[2] = CompanionContract{1};
        dismissed = 0;
        Group pair;
        pair.members = {1, 2}; pair.leader = 1;
        probe.OnDisband(&pair);
        check(dismissed == 1, "Disbanding the owner's bot-only group kept the companion");
        dismissed = 0;
        pair.members = {1, 3};
        probe.OnDisband(&pair);
        check(dismissed == 0, "Disbanding a group with another player dismissed companions");
        pair.bg = true; pair.members = {1, 2};
        probe.OnDisband(&pair);
        check(dismissed == 0, "Battleground disband dismissed companions");

        std::cout << "PASS: existing groups, raids, offline leaders, human authority, explicit leadership, master/leader split, leave-with-master, leave bot-only group\n";
    } catch (std::exception const& error) {
        std::cerr << "FAIL: " << error.what() << '\n'; return 1;
    }
}
'''


def run():
    module = Path(__file__).resolve().parents[1]
    cpp = (module / "src/CompanionRecruiter.cpp").read_text(encoding="utf-8")
    source = PREFIX
    for signature in ("void EnsureOwnerLeadsGroup(", "bool EnsureCompanionInGroup(", "Player* GetFollowTarget("):
        source += extract(cpp, signature).replace(" override", "") + "\n"
    for signature in ("void ReleaseOwnerCompanions(", "bool IsCompanionGuid(", "bool GroupHasOtherPlayer("):
        source += extract(cpp, signature) + "\n"
    source += "struct GroupScriptProbe {\n"
    for signature in ("void OnRemoveMember(Group* group, ObjectGuid guid", "void OnDisband(Group* group)"):
        source += extract(cpp, signature).replace(" override", "") + "\n"
    source += "};\n"
    source += CHECKS
    with tempfile.TemporaryDirectory(prefix="companion-group-test-") as directory:
        work = Path(directory)
        (work / "checks.cpp").write_text(source, encoding="utf-8")
        if os.name == "nt":
            vswhere = Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
            install = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip()
            if not install:
                raise RuntimeError("No MSVC compiler found")
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
    run()
