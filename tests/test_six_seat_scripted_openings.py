"""Six adopted scripted openings (Joshua, 2026-10-29, widget tap).

Pins the contract: each of the six non-Conductor seats' first meetings
opens with its adopted introduction VERBATIM, delivered at fresh start
only — never replayed on resume — via the Weaver mechanism
(MeetingService.start's fresh branch speaks definition.opening in
order). The recognition introduction stays live-generated; these tests
pin only the scripted opening. Weaver's opening is pinned unchanged.

EXPECTED is generated from the filed adoption doc, not hand-copied,
so a transcription slip cannot hide inside the test itself.
"""

import threading

import pytest

from local_ai.conversation import encounter as ENC
from local_ai.conversation.meeting import (
    MeetingService,
    MeetingStore,
    _seat_keystone_tasks,
)
from local_ai.conversation.store import ConversationStore
from local_ai.council import meetings as MT
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import service as ve
from local_ai.vision_execution.models import TaskUpdate


@pytest.fixture()
def ve_ctx(tmp_path, monkeypatch):
    """Isolate the vision-execution SQLite DB per test (test_meetings pattern)."""
    import local_ai.vision_execution.storage as ve_store

    monkeypatch.setattr(ve_store, "_DB_PATH", tmp_path / "ve.db")
    monkeypatch.setattr(ve_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(ve_store, "_init_done_paths", set())
    monkeypatch.setattr(ve_store, "_thread_local", threading.local())
    return {}


def _svc(tmp_path):
    return MeetingService(
        ConversationStore(tmp_path / "conv.db"),
        MeetingStore(tmp_path / "meetings.db"),
    )


def _seeded_user(email):
    user = ve.create_user_account(email, "pw", "Seat")
    keystone_seeding.seed_meet_your_council(user["id"])
    return user["id"]


def _complete_conductor_k1(uid):
    tasks = _seat_keystone_tasks(uid, "conductor")
    assert tasks, "seeded user has no conductor keystone tasks"
    ve.update_task(tasks[0]["id"], TaskUpdate(status="Done"), uid)
    assert _seat_keystone_tasks(uid, "conductor")[0]["status"] == "Done"


def _voice_bodies(state):
    return [m["body"] for m in state["messages"] if m["role"] == "voice"]


EXPECTED = {

    "champion": (
        "Well, well! A fresh recruit! Or perhaps a seasoned veteran? Hard to tell. Some of the fiercest warriors I've known never carried a sword.",
        "Tell me, have you ever noticed how readily people will march into battle over the most trivial insults, yet surrender without a fight the very things they claim to hold sacred?",
        "Curious creatures, aren't we? We'll defend our pride to the death, then negotiate away our principles for a little peace and quiet.",
        "I've always admired those who know when to draw their swords. Though lately I've wondered whether the greater courage belongs to those who know when to put them down.",
        "After all, if victory costs us everything we set out to defend… what exactly have we won?",
    ),
    "maverick": (
        "Oh! Hello there. You're not lost, are you? Wonderful! Neither am I. Though I must confess, I've never been entirely certain where we're supposed to be going.",
        "Funny thing about maps. Someone draws a few lines, gives the mountains names, and suddenly everyone agrees that's what the world looks like.",
        "I've met people who wouldn't dream of taking a road that wasn't marked. Others insist the only honest journey is one without a map at all.",
        "Personally, I rather like maps. Especially the old ones, with sea monsters lurking just beyond the edges.",
        "Makes you wonder, though… were those monsters warnings about what lay beyond the known world? Or were they simply the cartographer's way of admitting he hadn't the faintest idea?",
        "And if that's the case… how much of what we call knowledge is just a particularly convincing drawing?",
    ),
    "mentor": (
        "Ah, there you are! Come, come. Mind the seedlings. They're terribly ambitious this year, and haven't yet learned to distinguish a footpath from an opportunity.",
        "Would you believe that some of the oldest trees in this garden began as seeds no larger than a fingernail? And some of the grandest specimens I've planted never survived their first winter.",
        "Funny business, growing things. Give them too little attention and they wither. Too much, and they never learn to weather a storm.",
        "I've known gardeners who measure their success by the size of their harvest. Others insist the real reward is in the tending.",
        "But I've always wondered about the seeds that never sprout. Were they failures? Or did they give something to the soil that the next generation couldn't have grown without?",
        "Perhaps not everything we cultivate is meant to bloom.",
    ),
    "guardian": (
        "Well, don't just stand there in the doorway! Come in, come in. There's a fire going, and I believe we've enough supper for another.",
        "Mind that third step. Been meaning to fix it. Though I suppose I've been saying that for years.",
        "You know, I've spent a good deal of my life building things meant to last. Strong foundations. Sturdy walls. A roof that keeps the weather where it belongs.",
        "Strange thing about a house, though. The stronger you build it, the more you come to appreciate the people who make it worth building.",
        "Some say a home is where you're safe. Others say it's where you're free to be yourself. I should think a proper home ought to be both.",
        "But I wonder sometimes… if the whole world came knocking at your door, asking for shelter, how would you decide who to let in?",
        "And what sort of home would it be if you turned them away?",
    ),
    "ambassador": (
        "Ah, a visitor! How lovely. I was just puzzling over a rather peculiar word. Perhaps you can help me.",
        "You see, there's a language in which the same word can mean both 'stranger' and 'guest.' Isn't that wonderful? One describes someone we don't know, and the other someone we've welcomed.",
        "I've spent years fascinated by the things that happen between people when they try to understand one another.",
        "Some believe that if we could only find the right words, every disagreement might be resolved. Others insist that certain differences are simply too profound to translate.",
        "I wonder whether understanding someone necessarily brings us closer to them.",
        "After all, it's entirely possible to understand another person's position perfectly… and still find yourself standing on the opposite side of a bridge.",
        "Perhaps the purpose of a bridge isn't to bring everyone to the same side.",
        "Perhaps it's simply to make the crossing possible.",
    ),
    "skeptic": (
        "Interesting.",
        "A stranger appears, and I'm expected to make an introduction. Very well. Though I should point out that 'stranger' is already an assumption. For all I know, we've met before.",
        "Unlikely, perhaps. But unlikely and impossible are two very different things.",
        "I've spent much of my time investigating the peculiar confidence with which people believe things they cannot possibly know.",
        "Eyewitnesses contradict one another. Experts disagree. Entire civilizations have built magnificent monuments to ideas that turned out to be spectacularly wrong.",
        "And yet, occasionally, someone notices a small inconsistency. A detail everyone else overlooked. One stubborn fact that refuses to fit.",
        "I find those moments rather exhilarating.",
        "But here's a question that's been troubling me: if every conclusion must remain open to revision, is certainty ever justified?",
        "And if it isn't… how certain should I be of that?",
    ),
}


_SEAT_NAMES = (
    "Firebrand", "Champion", "Fox", "Maverick", "Gardener", "Mentor",
    "Bear", "Guardian", "Crane", "Ambassador", "Raven", "Skeptic",
    "Weaver", "Conductor",
)


def test_definitions_carry_adopted_openings_verbatim():
    """Script and authored definition both carry the adopted text whole."""
    for arch, opening in EXPECTED.items():
        script = MT.get_script(arch, 1)
        assert script is not None, arch
        assert script.opening == opening, arch
        assert ENC.get_definition(script).opening == opening, arch


def test_openings_name_no_seat():
    """Introductions are earned, not announced: no name or role anywhere."""
    for arch, opening in EXPECTED.items():
        joined = "\n".join(opening)
        for name in _SEAT_NAMES:
            assert name not in joined, (arch, name)


@pytest.mark.parametrize("arch", ["champion", "maverick", "mentor",
                                  "guardian", "ambassador", "skeptic"])
def test_start_delivers_opening_verbatim_and_resume_does_not_repeat(
    ve_ctx, tmp_path, arch,
):
    """Fresh start speaks the adopted bubbles in order; a resume repeats none."""
    uid = _seeded_user(f"{arch}@example.com")
    _complete_conductor_k1(uid)
    svc = _svc(tmp_path)
    state = svc.start(uid, arch)
    assert state["status"] == "active"
    assert _voice_bodies(state) == list(EXPECTED[arch])
    resumed = svc.start(uid, arch)
    assert _voice_bodies(resumed) == list(EXPECTED[arch])


def test_weaver_opening_unchanged():
    """The adoption touches the six seats only: Weaver's opening is byte-identical."""
    script = MT.get_script("conductor", 1)
    assert script.opening == MT.WEAVER_INTRODUCTION
    assert len(script.opening) == 4
    assert ENC.get_definition(script).opening == MT.WEAVER_INTRODUCTION
