# People & Capacity tab — functionality, workflows, links and relationships

This document defines the **People & Capacity** tab in the Vision Execution Engine: what it does, how it works, and how it connects to the rest of the system.

---

## 1. Purpose

The tab is the **human-capability layer** of execution:

- **People** = persons who can fill roles, own work, or steward resources.
- **Capacity** = how much time each person has (weekly hours) and how much is already committed to active/ready projects (derived).

It answers: *who is available, who is doing what, and who is over-committed.*

---

## 2. Data model (existing)

### Person (stored)

- **id**, **name**, **role**, **relationship_type**
- **contact_info**, **strengths**, **needs**, **wants**, **availability**, **notes**
- **created_at**, **updated_at**

### Capacity profile (stored, one per person)

- **person_id** (PK, FK → persons)
- **weekly_capacity_hours** (number)
- **created_at**, **updated_at**

### Capacity profile (derived on read, not stored)

- **activeWeeklyHours** — sum of `project.estimated_weekly_hours` for projects where the person is **owner_id** or in **supporting_owner_ids**, and project status is **Ready** or **Active**.
- **capacityDelta** — `activeWeeklyHours - weekly_capacity_hours` (positive = over-committed).
- **overcapacity** — `true` when `capacityDelta > 0`.

Derived fields are computed in the backend (`local_ai.vision_execution.derived.add_capacity_derived`) when listing or fetching capacity profiles; they are not persisted.

---

## 3. Tab functionality

### 3.1 List (left column)

- **Data:** `persons` from `GET /vision-execution/persons`, plus `capacityProfiles` from `GET /vision-execution/capacity-profiles` (with derived fields).
- **UI:** Scrollable list of cards; each shows **name**, optional **role**, and optional **Capacity: Xh/wk** from the person’s capacity profile.
- **Selection:** Click a person → open **Person detail panel** (right); `detailPersonId` is set.

### 3.2 Create person

- **Trigger:** “Add person” button → **CreatePersonForm** (inline).
- **Form:** Name (required), Role (optional).
- **Submit:** `POST /vision-execution/persons` with `{ name, role }` → then `fetchPersons()`; form closes. No capacity profile is created by default (user can add one in the detail panel).

### 3.3 Person detail panel

- **Load:** `GET /vision-execution/persons/{personId}`; capacity value comes from `capacityProfiles.find(cp => cp.person_id === personId)` (already loaded with the tab).
- **Sections:**
  - **Basics** — Name, Contact info
  - **Role / relationship** — Role, Relationship type
  - **Capacity** — Weekly capacity (hours); number input. On save, sent via `PUT /vision-execution/capacity-profiles` with `{ person_id, weekly_capacity_hours }`. If derived data exists, shows: Active hrs/wk, Delta, Overcapacity (Yes/No).
  - **Strengths / needs / wants** — Strengths, Needs, Wants, Availability (textarea/field)
  - **Notes**
  - **Metadata / debug**
- **Actions:** Save (person PATCH + capacity PUT if hours entered), Cancel, Delete (with confirm).
- **Delete:** `DELETE /vision-execution/persons/{personId}`. Backend clears references: initiative `owner_id`, project `owner_id`, task `assignee_id`, asset `owner_id`; deletes capacity profile; then deletes the person.

---

## 4. API used by the tab

| Method | Path | Purpose |
|--------|------|--------|
| GET | `/persons` | List all persons (tab list). |
| GET | `/persons/{person_id}` | Get one person (detail panel). |
| POST | `/persons` | Create person (CreatePersonForm). |
| PATCH | `/persons/{person_id}` | Update person (detail panel Save). |
| DELETE | `/persons/{person_id}` | Delete person (and clear refs + capacity profile). |
| GET | `/capacity-profiles` | List all capacity profiles (with derived activeWeeklyHours, capacityDelta, overcapacity). |
| GET | `/capacity-profiles/{person_id}` | Get one profile (optional; tab usually uses list). |
| PUT | `/capacity-profiles` | Upsert capacity profile (body: `person_id`, `weekly_capacity_hours`). |

---

## 5. Links and relationships (where persons are used)

### 5.1 Work nodes → person (ownership / assignment)

- **Initiative** — `owner_id` → one person (optional). Shown in initiative detail; dropdown uses `persons`.
- **Project** — `owner_id` (optional), `supporting_owner_ids` (array of person ids). Owner and supporting owners in project detail; both drive **capacity**: that person’s `activeWeeklyHours` includes this project’s `estimated_weekly_hours` when status is Ready/Active.
- **Task** — `assignee_id` → one person (optional). Shown in task detail; dropdown uses `persons`.
- **Asset** — `owner_id` → one person (optional). Shown in asset detail; dropdown uses `persons`.

### 5.2 Initiative seats → person

- **Initiative seats** (role slots) — each seat has `assigned_person_id` (optional). In initiative “Resourcing reality”, seats list roles and assignees; assignee dropdown is `persons`. Seats are stored on the initiative (e.g. `initiative.seats`); they are **not** a separate table in the same way as capacity_profiles. Assigning a person to a seat does **not** by itself create or update a capacity profile; capacity is driven only by **project** ownership/supporting_owner and `estimated_weekly_hours`.

### 5.3 Capacity profile → projects

- Capacity **derived** fields depend on **projects**: for each person, the backend sums `estimated_weekly_hours` of projects where the person is owner or in supporting_owner_ids and status is Ready/Active. So: **projects** link to **persons** via owner/supporting; **capacity** is then computed from **projects** and **weekly_capacity_hours**.

### 5.4 Meeting extraction / commit

- **Extraction** can emit **people** (person references). In **Review**, each staged item (idea, initiative, project, task, asset, person) can have **assignedPersonIds** (and assignedAssetIds).
- **Commit** semantics for persons:
  - **Create person:** Staged item of kind “person” → `POST /persons` (name, role, notes, traceability).
  - **Assign to other entities:** For initiative/project/task/asset, first id in `assignedPersonIds` → **owner_id** or **assignee_id** on the created entity. So linking “who” at commit time uses the same person records that appear in People & Capacity.

### 5.5 Radar

- **Overcapacity** bucket: built from capacity profiles where `overcapacity === true`; each item is a **person** (id, name) with active hours and capacity hours. So the **People & Capacity** data (persons + capacity profiles with derived overcapacity) feeds the **Radar** “Overcapacity” list.

### 5.6 Executive view

- **Overcapacity** section: uses `capacityProfiles.filter(c => c.overcapacity)` and resolves person name from `persons`; shows “Name — activeHrs / capacityHrs”. Same source as Radar; no separate API.

---

## 6. Workflows (user journeys)

1. **Add a person**  
   People & Capacity tab → Add person → enter name (and optional role) → Save → person appears in list. Optionally open person → set **Capacity** (weekly hours) and Save.

2. **Assign someone to work**  
   From Initiative / Project / Task / Asset detail: choose **Owner** or **Assignee** (or seat assignee) from dropdown; dropdown is the same `persons` list. Save the work node. That person’s **capacity** (if they have a profile) will now include that project’s hours when status is Ready/Active.

3. **See who is over-committed**  
   People & Capacity tab: open a person; if they have a capacity profile and derived data, **Overcapacity** and **Delta** show. Alternatively: **Radar** → Overcapacity, or **Executive view** → Overcapacity.

4. **Delete a person**  
   Person detail → Delete → confirm. Backend clears all owner_id/assignee_id references and deletes the capacity profile, then the person. Work nodes and assets remain; their owner/assignee field becomes null.

5. **Meeting extraction creates/assigns people**  
   Meeting Capture → extract → Review → assign people to initiatives/projects/tasks/assets (or create new “person” items and commit). Commit creates persons and/or sets owner_id/assignee_id on created work nodes. Those persons then appear in People & Capacity.

---

## 7. Summary diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  People & Capacity tab                                           │
│  • List: persons + capacity (weekly hours, optional derived)   │
│  • Create: POST /persons                                         │
│  • Detail: PATCH /persons, PUT /capacity-profiles, DELETE person │
└─────────────────────────────────────────────────────────────────┘
         │
         │ persons[] (id, name, role, …)
         │ capacityProfiles[] (person_id, weekly_capacity_hours, + derived)
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Where persons are referenced                                    │
│  • Initiative: owner_id; seats[].assigned_person_id              │
│  • Project: owner_id, supporting_owner_ids  → drives capacity   │
│  • Task: assignee_id                                             │
│  • Asset: owner_id                                               │
└─────────────────────────────────────────────────────────────────┘
         │
         │ Projects (Ready/Active) + estimated_weekly_hours
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Capacity derived (backend)                                      │
│  • activeWeeklyHours = sum(project hours for owner/supporting)    │
│  • capacityDelta = active - weekly_capacity_hours                 │
│  • overcapacity = delta > 0                                       │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Radar (overcapacity bucket) & Executive view (Overcapacity)   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. Limitations and notes

- **Capacity is project-based only.** Initiative seats (role + assignee) do not feed `activeWeeklyHours`; only project owner/supporting_owner and `estimated_weekly_hours` do. So “capacity” here means *committed project time* vs *stated weekly hours*.
- **No “person detail” from work nodes.** The People tab does not show “initiatives/projects/tasks where this person is owner/assignee” in one place; that would require aggregation (possible future improvement).
- **Tab load:** When the user opens the People tab, the app fetches `persons` and `capacity-profiles`; capacity-profiles are returned with derived fields from the backend (which loads projects to compute them).
- **Single capacity profile per person.** One row in `capacity_profiles` per person; upsert by `person_id`. No date ranges or historical capacity in the current model.
