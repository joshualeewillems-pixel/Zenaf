"""The lens library — canonical data, not code (Steward S0).

A *lens* is an interpretive framework a thread's story may be read
through: a named, attributed narrative structure with phases,
observable fit signals, and — load-bearing — its own cautions. This
module is the library *as data*, in the jurisdictions.py pattern: a
static tuple of records a component can serve, with no behavior
attached. Fitting discipline (proposal → offer → user verdict,
durable rejection, one live fitting per thread) lives in the store
and in later phases; S0 ships the schema and a v1 canon.

The v1 contents follow the audit's Part V recommendation: a small
canon Joshua can defend line by line (the monomyth; a cyclical /
seasonal lens; a descent-and-return; an ordeal / tempering), each
with honest cautions, growing by his edit. A lens library that
outruns its editor becomes imposition with good typography — so
every entry carries ``source_note`` attribution as data: whose
formulation this is, never an anonymous "the pattern."

Scale and progression (ratified 2026-10-23, Part IX of the audit):
a lens carries a *progression template* (its phases) that a reading
may apply AT any scale. The phases are descriptive — what a phase
looks for, and questions that open it — never a mandatory sequence
a thread must traverse. A reading's progression position names one
phase of one lens, or is recorded as unknown / inapplicable
(models.ProgressionPosition); the library does not rank or order
anyone's life.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LensPhase:
    """One movement in a lens's progression template.

    ``what_it_looks_for`` describes the phase in evidence terms — what
    would actually be visible in a user's material if this movement
    were present. ``guiding_questions`` are the questions the phase
    opens for a reading, never a script a seat must deliver.
    """

    name: str
    what_it_looks_for: str
    guiding_questions: tuple[str, ...] = ()


@dataclass(frozen=True)
class NarrativeLens:
    """One interpretive framework in the library."""

    id: str
    name: str
    tradition: str  # mythology | religion | philosophy |
                    # archetypal psychology | literary | ecological
    source_note: str  # whose formulation this is — attribution is data
    phases: tuple[LensPhase, ...]
    fit_signals: tuple[str, ...]  # observable evidence shapes
    cautions: tuple[str, ...]  # known misfits — shown WITH any proposal
    seat_affinity: tuple[str, ...] = ()  # routing hint, NOT a permission

    def phase_names(self) -> tuple[str, ...]:
        return tuple(phase.name for phase in self.phases)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "tradition": self.tradition,
            "source_note": self.source_note,
            "phases": [
                {
                    "name": p.name,
                    "what_it_looks_for": p.what_it_looks_for,
                    "guiding_questions": list(p.guiding_questions),
                }
                for p in self.phases
            ],
            "fit_signals": list(self.fit_signals),
            "cautions": list(self.cautions),
            "seat_affinity": list(self.seat_affinity),
        }


LENSES: tuple[NarrativeLens, ...] = (
    NarrativeLens(
        id="departure_initiation_return",
        name="Departure, Initiation, Return — the Hero's Journey",
        tradition="mythology",
        source_note=(
            "Joseph Campbell's monomyth (The Hero with a Thousand "
            "Faces, 1949), in Christopher Vogler's writer's adaptation "
            "(The Writer's Journey). A modern synthesis of mythic "
            "material, not a universal law of lives."
        ),
        phases=(
            LensPhase(
                name="departure",
                what_it_looks_for=(
                    "A threshold crossed or refused: the user leaves — "
                    "or is pushed out of — an ordinary arrangement, "
                    "often with a call they did not choose."
                ),
                guiding_questions=(
                    "What arrangement ended, or is ending?",
                    "Was the leaving chosen, refused, or imposed?",
                ),
            ),
            LensPhase(
                name="initiation",
                what_it_looks_for=(
                    "Trials that test the departure's premise: allies "
                    "and opponents appear, early wins prove hollow, "
                    "and the central ordeal forces a change in the "
                    "user rather than in their circumstances."
                ),
                guiding_questions=(
                    "What has the road demanded that staying home "
                    "would not have?",
                    "What did the hardest moment change in you, not "
                    "around you?",
                ),
            ),
            LensPhase(
                name="return",
                what_it_looks_for=(
                    "The user comes back — to a place, a role, a "
                    "community — carrying something the departure "
                    "cost them to earn, and must decide what it is "
                    "for."
                ),
                guiding_questions=(
                    "What do you have now that the beginning of this "
                    "did not?",
                    "Who is it for, besides you?",
                ),
            ),
        ),
        fit_signals=(
            "a named leaving: a job, place, role, or relationship "
            "exited or being exited",
            "ordeal language around a central difficulty, with stakes "
            "the user names themselves",
            "return imagery: going back, bringing something home, "
            "being received differently",
        ),
        cautions=(
            "Imposes a single-arc shape on cyclical or seasonal "
            "material — most lives have several departures, not one.",
            "Hero framing can inflate ordinary endurance into destiny "
            "and make rest look like failure.",
            "Assumes return is desirable; sometimes the right reading "
            "is that there is no way back and none is wanted.",
            "Campbell's synthesis is contested even as mythology — "
            "offer it as one formulation, never as the shape of "
            "stories as such.",
        ),
        seat_affinity=("champion", "conductor"),
    ),
    NarrativeLens(
        id="descent_and_return",
        name="Descent and Return — katabasis",
        tradition="mythology",
        source_note=(
            "The katabasis tradition: Inanna's descent to the "
            "underworld (Sumerian), Orpheus, Jonah. Formulated here "
            "as a pattern of going down stripped and coming back "
            "changed; religious resonances are the traditions' own "
            "and are never assigned by the system."
        ),
        phases=(
            LensPhase(
                name="descent",
                what_it_looks_for=(
                    "A downward movement the user did not script: "
                    "loss, illness, failure, or collapse narrowing "
                    "life gate by gate, each gate costing something "
                    "they carried."
                ),
                guiding_questions=(
                    "What has been taken, gate by gate?",
                    "What is still in your hands?",
                ),
            ),
            LensPhase(
                name="the_bottom",
                what_it_looks_for=(
                    "The lowest point named as such: nothing left to "
                    "perform with, help absent or refused, the old "
                    "identity no longer load-bearing."
                ),
                guiding_questions=(
                    "What stopped working down there?",
                    "What, if anything, was true at the bottom that "
                    "wasn't visible at the top?",
                ),
            ),
            LensPhase(
                name="ascent",
                what_it_looks_for=(
                    "A return upward that does not restore the "
                    "starting point: the user re-enters ordinary life "
                    "carrying the descent's knowledge, often more "
                    "slowly and selectively than they left it."
                ),
                guiding_questions=(
                    "What are you not carrying back up?",
                    "What does the surface look like from here?",
                ),
            ),
        ),
        fit_signals=(
            "loss or collapse described as a downward journey, in "
            "the user's own spatial language",
            "stripping imagery: roles, capacities, or certainties "
            "removed in sequence",
            "a named lowest point, and speech from after it that "
            "differs from speech before it",
        ),
        cautions=(
            "Can romanticize suffering — a descent is not ennobling "
            "by default, and some descents have no ascent in view.",
            "Not every low period is a katabasis; ordinary grief and "
            "ordinary depression are not failed myths.",
            "Religious resonance cuts both ways: for some users this "
            "frame is sacred, for others it is exactly the story "
            "they are trying to stop being told about them.",
        ),
        seat_affinity=("skeptic", "guardian"),
    ),
    NarrativeLens(
        id="sowing_growth_harvest_fallow",
        name="The Seasonal Round — sowing, growth, harvest, fallow",
        tradition="ecological",
        source_note=(
            "Agrarian seasonal cycles, and the Demeter–Persephone "
            "myth that encodes them: what is planted, tended, "
            "gathered, and rested, in that order, every year, "
            "without any season being the point of the others."
        ),
        phases=(
            LensPhase(
                name="sowing",
                what_it_looks_for=(
                    "Deliberate beginnings made before any evidence "
                    "they will work: seeds chosen, ground prepared, "
                    "commitments planted in the dark."
                ),
                guiding_questions=(
                    "What are you planting before you can know?",
                    "What did you choose not to plant this season?",
                ),
            ),
            LensPhase(
                name="growth",
                what_it_looks_for=(
                    "Tending work: slow, repetitive, mostly "
                    "unwitnessed care while outcomes are still "
                    "uncertain and weather is not cooperating."
                ),
                guiding_questions=(
                    "What are you tending that nobody sees?",
                    "What does this season ask that last season "
                    "didn't?",
                ),
            ),
            LensPhase(
                name="harvest",
                what_it_looks_for=(
                    "Gathering what actually grew — which is never "
                    "exactly what was planted — and deciding what it "
                    "feeds, what is stored, and what is seed for next "
                    "year."
                ),
                guiding_questions=(
                    "What grew that you didn't plant?",
                    "What of this is seed, and what is supper?",
                ),
            ),
            LensPhase(
                name="fallow",
                what_it_looks_for=(
                    "Rest that is part of the cycle, not an exit from "
                    "it: ground recovering its capacity, the user "
                    "deliberately not producing, fertility returning "
                    "unforced."
                ),
                guiding_questions=(
                    "What is the fallow restoring?",
                    "What are you protecting by not planting?",
                ),
            ),
        ),
        fit_signals=(
            "work or care described in seasons, cycles, or returns "
            "rather than in a single arc",
            "beginnings, tendings, and endings coexisting in the "
            "same material at once",
            "rest described — or conspicuously not described — as "
            "part of the work",
        ),
        cautions=(
            "Fallow reads as failure under productivity frames; the "
            "lens must never be used to shame a fallow season or to "
            "dignify an enforced one.",
            "Seasonal time is slow: the lens fits ill where the "
            "material is genuinely urgent or deadline-bound.",
            "A cycle has no climax; users mid-crisis may hear "
            "'this is just a season' as dismissal.",
        ),
        seat_affinity=("mentor",),
    ),
    NarrativeLens(
        id="ordeal_and_tempering",
        name="Trial and Tempering — the forge",
        tradition="archetypal psychology",
        source_note=(
            "The forge and alchemical traditions of transformation "
            "by heat and pressure: metal is not decorated by the "
            "fire but changed by it, and can also be ruined by it — "
            "both halves are in the tradition, and both stay in "
            "this formulation."
        ),
        phases=(
            LensPhase(
                name="heating",
                what_it_looks_for=(
                    "Pressure applied that the material cannot ignore: "
                    "a demand, exposure, or deadline under which the "
                    "user's existing shape stops holding."
                ),
                guiding_questions=(
                    "What is the heat, exactly — and who set it?",
                    "What shape is no longer holding?",
                ),
            ),
            LensPhase(
                name="working",
                what_it_looks_for=(
                    "Repeated testing under the pressure: attempts, "
                    "failures, adjustments — the user being worked on "
                    "and working back, blow by blow."
                ),
                guiding_questions=(
                    "What has each blow taught that the last one "
                    "hadn't?",
                    "Where is it thinning instead of strengthening?",
                ),
            ),
            LensPhase(
                name="setting",
                what_it_looks_for=(
                    "The pressure lifts and the new shape holds — or "
                    "cracks: the user discovers what the ordeal "
                    "actually made of them by what they can now do, "
                    "and what they no longer can."
                ),
                guiding_questions=(
                    "What held? What cracked?",
                    "Would you choose the fire again, knowing?",
                ),
            ),
        ),
        fit_signals=(
            "sustained pressure with the user's own language of "
            "testing, proving, or being forged",
            "repeated attempts against the same resistance, with "
            "visible adjustment between them",
            "an aftermath the user describes in terms of changed "
            "capacity, for better or worse",
        ),
        cautions=(
            "Can sanctify avoidable harm — 'the fire is good for "
            "you' is a sentence abusers also say; the lens never "
            "justifies the source of the heat.",
            "Endurance is not automatically virtue: some ordeals "
            "should be escaped, not tempered by.",
            "The forge implies a smith; where no agent is shaping "
            "the trial, the frame can invent purpose that chaos "
            "does not have.",
        ),
        seat_affinity=("champion", "guardian"),
    ),
)


def get_lens(lens_id: str) -> NarrativeLens | None:
    """The lens with this id, or None — lookups never invent lenses."""
    for lens in LENSES:
        if lens.id == lens_id:
            return lens
    return None


def lens_ids() -> tuple[str, ...]:
    return tuple(lens.id for lens in LENSES)
