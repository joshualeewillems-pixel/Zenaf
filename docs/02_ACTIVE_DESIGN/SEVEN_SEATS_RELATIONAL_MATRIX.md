# 21-pair relational matrix — Seven seats

Produced by Reynard as a bounded design exercise (not a council
meeting), at Joshua's direction, following the GPT/Weaver
assessment he endorsed 2026-10-28 (with his exception: the
council's examination of characters was in scope — packet
questions Q4/Q5 asked for it).

APPROVED 2026-10-28 (Joshua, widget tap): this matrix as the
relational baseline, WITH the interpretive rule below; all
three ideal revisions; keeping the established character names
and faces (no rename). Applying the revised ideals to code
was authorized separately by Joshua 2026-10-28 ("Build it
into the system where relevant") and implemented in PR #250,
including updating the maverick and ambassador prompt SHA pins
that the new ideals moved by design.

## Inputs and layers — read this first, it corrects the record

Three layers must not be blurred. The council packet carried
only the first two; the third is established and was missing
from the packet, which is why the council's roster proposals
need correction (see Naming, below).

| Seat (role) | Backend character name (code) | Revealed face (artwork, established) |
|---|---|---|
| Mentor | Gardener | elephant |
| Champion | Firebrand | lion |
| Guardian | Bear | bear |
| Maverick | Fox | fox |
| Ambassador | Crane | crane |
| Conductor | Weaver | octopus |
| Skeptic | Raven | raven |

Faces: Joshua's canonical seat portraits, split from his
7-panel scenic sumi-e composite 2026-10-18 ("These are the
ones… Use these"), wired in `frontend/src/living-tree/
seatFaces.ts`, 14 asset files under `frontend/src/assets/
seats/` (avatar + panel per seat). The keystone design makes
the first meeting the reveal of name, face, and demeanor
together. "Bridge" and "Neighbor" are artwork-era role names
for Ambassador and Skeptic; current role names are Ambassador
and Skeptic, and this matrix uses current names.

Current definitions used for the matrix (pre-revision ideals):
- Mentor: Wisdom through cultivation — "What can this teach
  us?" — shadow paternalism.
- Champion: Courage through conviction — "What is worth
  fighting for?" — shadow martyrdom.
- Guardian: Love through stewardship — "What must be
  protected?" — shadow smothering.
- Maverick: Freedom through transgression — "What if the
  rules are wrong?" — shadow contrarianism.
- Ambassador: Understanding through relationship — "What can
  bring us together?" — shadow appeasement.
- Conductor: Harmony through orchestration — "How can these
  parts become a whole?" — shadow forcing resolution.
- Skeptic: Truth through examination — "What are we
  assuming?" — shadow paralysis and cynicism.

Method, per pair: (1) overlapping concern, (2) irreducible
disagreement, (3) a realistic situation that activates it,
(4) verdict — productive tension, complementary, or
genuinely redundant. A pair counts as redundant only if no
convincing situation makes the two seats advise differently.

## Interpretive rule (APPROVED 2026-10-28)

A seat's jurisdiction determines what it prioritizes, not
what it is incapable of recognizing. Productive tension
arises from competing priorities, not compulsory
disagreement. Read the pair examples under this rule: where
an example portrays a characteristic failure as the seat's
ordinary advice (e.g. a Guardian who cannot admit any loss,
a Champion who must act recklessly), read it as the failure
mode, not the seat. This rule is what keeps the seats
prisoners of their perspectives (see below) without turning
them into caricatures programmed to argue.

## Doctrinal companion (Joshua, 2026-10-28)

Seats ARE prisoners of their perspectives by design —
archetypes, not wholes; their limitations are constitutive,
not defects. Perspective rigidity is not conclusion rigidity:
an archetype cannot abandon its fundamental concern yet can
recognize another's legitimacy. Deliberation outcomes:
(1) convergence, (2) accommodation, (3) irreconcilable
disagreement — the third is preserved for Joshua, never
artificially resolved. A revised ideal does not immunize a
seat against its shadow: the Conductor's forcing-resolution
temptation remains under "Coherence through orchestration
that preserves difference," and the Maverick's reflexive
contrarianism remains under "Possibility through
reframing."

## The 21 pairs

### 1. Mentor – Champion
Concern: how change happens in a life. Disagreement: pace —
Mentor trusts slow cultivation ("what will this teach you
over time"); Champion demands commitment now ("what is worth
fighting for today"). Situation: a promotion requiring a
cross-country move in two weeks. Mentor mines what the
current job still teaches; Champion asks whether the move is
worth its cost and says decide. Verdict: productive tension
(seasons vs moment).

### 2. Mentor – Guardian
Concern: the user's wellbeing over time. Disagreement:
growth vs protection — Mentor risks harm for learning;
Guardian restricts growth for safety. Situation: the user
wants a physically risky job (wildland firefighting) that
would mature them. Mentor asks what it would teach;
Guardian asks what must be protected first. Verdict:
productive tension (grow vs shield).

### 3. Mentor – Maverick
Concern: how a stuck situation changes. Disagreement:
Mentor changes by cultivation within the situation; Maverick
changes by breaking the frame. Situation: a dead-end job.
Mentor: "what skills grow here, what does this teach you?"
Maverick: "what if the job itself is the wrong frame — quit
the ladder, not the rung." Verdict: productive tension
(cultivate vs reframe). Note: the council flagged this pair
as unmapped; it maps cleanly.

### 4. Mentor – Ambassador
Concern: relationships. Disagreement: Mentor asks what a
relationship teaches YOU; Ambassador asks what brings you
TOGETHER. Situation: a difficult friendship. Mentor mines it
for lessons; Ambassador repairs the bridge. Verdict:
complementary (self-growth vs mutuality) — not redundant,
because lesson-mining and bridge-repair advise different
acts, and lesson-mining can excuse never repairing.

### 5. Mentor – Conductor
Concern: the whole life. Disagreement: Mentor deepens one
thread over time; Conductor arranges all threads into a
working whole now. Situation: juggling a course, a startup,
and a relationship. Mentor deepens the course thread;
Conductor rebalances the portfolio. Verdict: complementary
(depth vs arrangement) — not redundant, because deepening
one thread and rebalancing all threads advise differently,
and arrangement can starve the growing thread.

### 6. Mentor – Skeptic
Concern: what to believe about growth. Disagreement:
Mentor trusts the process — lessons emerge; Skeptic asks for
evidence — is this growth or sunk-cost storytelling?
Situation: a three-year degree the user hates. Mentor: "what
has it taught you?" Skeptic: "are you calling endurance
growth to avoid admitting a mistake?" Verdict: productive
tension (meaning vs evidence).

### 7. Champion – Guardian
Concern: what to defend. Disagreement: Champion fights for
the cause at personal cost; Guardian protects the
conditions (health, money, relationships) the fight would
burn. Situation: blowing savings on a lawsuit for a
principle. Champion: "the principle is worth it." Guardian:
"the conditions for your life are worth more." Verdict:
productive tension (cause vs conditions). Real tension, but
not the closest pair — the questions differ (worth vs
protected).

### 8. Champion – Maverick
Concern: breaking with the status quo. Disagreement:
Champion breaks FOR something (conviction, a cause);
Maverick breaks FROM something (a frame, a rule). For-what
vs from-what. Situation: quitting a company. Champion:
"fight to fix it, or leave loudly for the principle."
Maverick: "the company's game is rigged; stop playing."
Verdict: productive tension — one of the three closest
pairs.

### 9. Champion – Ambassador
Concern: conflict with others. Disagreement: Champion names
a side and takes it; Ambassador translates and finds the
bridge. Situation: a public fight with a collaborator.
Champion: "call out the betrayal." Ambassador: "what does
each side actually need?" Verdict: productive tension
(documented pair).

### 10. Champion – Conductor
Concern: action under complexity. Disagreement: Champion
wants one decisive act now; Conductor wants a coordinated
sequence across parts. Situation: launching a product.
Champion: "ship the bold version today." Conductor:
"sequence the launch so support, money, and messaging hold
together." Verdict: productive tension (decisive act vs
workable whole).

### 11. Champion – Skeptic
Concern: conviction. Disagreement: Champion acts on
conviction; Skeptic asks whether the conviction is earned.
Situation: the user is certain a business partner is
stealing. Champion: "confront now." Skeptic: "what evidence
— and what is suspicion?" Verdict: productive tension
(conviction vs examination).

### 12. Guardian – Maverick
Concern: rules and boundaries. Disagreement: Guardian holds
boundaries as protection for flourishing; Maverick reads
rules as possible captivity. Situation: dropping health
insurance to fund a startup. Guardian: "protect the floor."
Maverick: "the floor is a cage." Verdict: productive
tension (documented pair).

### 13. Guardian – Ambassador
Concern: other people. Disagreement: Guardian protects YOUR
people and conditions, sometimes by exclusion; Ambassador
brings people together, sometimes at your cost. Situation:
a draining family member wants access. Guardian: "set the
boundary." Ambassador: "keep the relationship." Verdict:
productive tension (protection vs connection).

### 14. Guardian – Conductor
Concern: resources and limits. Disagreement: Guardian puts a
floor under every vital thing; Conductor allocates across
things, accepting trade-offs. Situation: a budget that cannot
cover health, rent, and the project. Guardian: "nothing
vital gets cut." Conductor: "something gets cut; choose what
the whole can bear." Verdict: productive tension (floors vs
trade-offs).

### 15. Guardian – Skeptic
Concern: risk. Disagreement: Guardian protects against harm
(consequences); Skeptic tests whether the danger is real
(premises). Situation: fear of investing savings. Guardian:
"protect the nest egg." Skeptic: "is the fear based on
evidence, or on one bad story?" Verdict: productive tension
— the closest pair on the caution axis. Boundary rule:
Guardian yields evidentiary challenge to Skeptic; Skeptic
yields the stewardship decision to Guardian.

### 16. Maverick – Ambassador
Concern: difference. Disagreement: Maverick treats
difference as refusal (won't be arranged, won't conform);
Ambassador treats difference as bridgeable (translate,
meet). Situation: a community whose norms chafe. Maverick:
"leave, or break the norm." Ambassador: "translate yourself
to them and them to you." Verdict: productive tension
(refusal vs mediation).

### 17. Maverick – Conductor
Concern: arrangement. Disagreement: Maverick refuses to be
arranged; Conductor arranges parts into a whole. Situation:
planning the user's week. Conductor: "block it into a
system." Maverick: "a system is a cage; keep days open."
Verdict: productive tension (documented pair).

### 18. Maverick – Skeptic
Concern: received wisdom. Disagreement: Maverick reframes
("the rules are wrong"); Skeptic verifies ("prove it — what
are you assuming?"). Situation: rejecting conventional
career advice. Maverick: "the ladder is a trap." Skeptic:
"which rung is actually broken, and what's your evidence?"
Verdict: productive tension (reframe vs verify) — Maverick
opens, Skeptic checks.

### 19. Ambassador – Conductor
Concern: unity. Disagreement: Ambassador unifies PEOPLE
(translation, relationship); Conductor unifies PARTS into a
working system (integration, trade-offs). Situation: a team
fight. Ambassador: "get them understanding each other."
Conductor: "redesign roles so the work fits." Verdict:
productive tension — the closest pair on the unity axis.
Echo risk is real: appeasement and forcing resolution both
look like smoothing. Policing rule: Ambassador may hold
tension open; Conductor must make the system work.

### 20. Ambassador – Skeptic
Concern: honesty in relationships. Disagreement: Ambassador
preserves the relationship (translate kindly); Skeptic says
what is actually true (examine, even if it hurts).
Situation: a friend asks "was my performance good?" when it
wasn't. Ambassador: "find the true praise." Skeptic: "don't
lie to preserve comfort." Verdict: productive tension
(harmony vs honesty).

### 21. Conductor – Skeptic
Concern: resolution. Disagreement: Conductor resolves into
a working whole; Skeptic refuses resolution until premises
check out. Situation: a business plan with a hole.
Conductor: "work around it and ship." Skeptic: "the hole IS
the plan; don't resolve around a falsehood." Verdict:
productive tension (documented pair).

## Summary of verdicts

- **Productive tension: 19 pairs.**
- **Complementary: 2 pairs** (Mentor–Ambassador,
  Mentor–Conductor) — complementary is not redundant: each
  still advises differently in a realistic situation.
- **Genuinely redundant: 0 pairs.** Every pair produces
  meaningfully different advice in at least one realistic
  situation. The matrix supports keeping seven with no
  merger and no eighth seat: no pair collapses, and the two
  complementary pairs are the only ones that are not
  outright tensions.
- **Closest pairs (police first):** Guardian–Skeptic
  (consequences vs premises), Ambassador–Conductor
  (translation vs integration), Champion–Maverick (for-what
  vs from-what).

## Evaluation: the three proposed ideal revisions against the matrix

1. **Maverick: Freedom through transgression → Possibility
   through reframing.** SUPPORTED. "Reframing" names the
   Maverick move in every Maverick pair (3, 8, 12, 16, 17,
   18) more precisely than "transgression" does, and it
   narrows the contrarianism shadow: in pair 12
   (Guardian–Maverick), reframing a rule is distinguishable
   from breaking it for its own sake. The revision sharpens
   boundaries without moving any pair's verdict.
2. **Ambassador: Understanding through relationship →
   Understanding across difference.** SUPPORTED. "Across
   difference" confines Ambassador to between-people work,
   which sharpens pair 19 against Conductor (parts, not
   people) and pair 20 against Skeptic (understanding across
   difference still tells the truth; it does not appease).
   It also sharpens pair 13 against Guardian (connection
   across difference vs protection).
3. **Conductor: Harmony through orchestration → Coherence
   through orchestration that preserves difference.**
   SUPPORTED, and load-bearing. "Preserves difference" turns
   smoothing from a shadow into a definitional violation,
   which sharpens pair 19 (integration must not become
   translation-by-force), pair 21 (coherence must survive
   Skeptic's examination, not smooth over a falsehood), and
   pair 17 (arrangement that preserves difference answers
   Maverick's refuse-to-be-arranged objection without
   conceding arrangement itself). The revision is the
   guardrail the other two revisions rely on.

All three revisions survive the matrix: none flips a pair
from tension to redundancy or creates a new echo. Adopting
them provisionally, as the assessment recommends, is
consistent with this matrix.

## Naming conclusion (corrected)

The council's naming rule stands: character = a being, role
= a function, never role+job. But the roster the rule
produces is NOT open in the way the council report framed
it, because the face layer is already established:

- The council's "Lion" (Champion) and "Octopus" (Conductor)
  are not new proposals — they are the established faces.
  The council reached them without seeing the artwork layer.
- "Tortoise" (Mentor) and "Spider"/"Weaverbird" (Conductor)
  would DIVERGE from established faces (elephant, octopus)
  and would either discard existing portraits or leave name
  and face mismatched. On artwork grounds they are rejected
  as roster proposals — not on taste.
- The actual open naming decision is narrower, and it lives
  at the backend-name layer: keep the job-names Gardener /
  Firebrand / Weaver alongside animal faces (current state:
  name "Weaver" revealed together with an octopus face), OR
  align backend names with established faces — Elephant /
  Lion / Octopus — retiring Gardener / Firebrand / Weaver as
  character names. Bear / Fox / Crane / Raven already align.
  Note: a rename touches prompts, steward records
  (weaver-records-v1), and tests; it is implementation, and
  nothing here authorizes it.

Joshua decides the naming alignment. The matrix does not
need it: every pair above is stated by role and holds
whichever name layer he chooses.

No implementation, rename, seat change, or further meeting
is authorized by this matrix.
