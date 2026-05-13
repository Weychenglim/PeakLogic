# Optimization Assumptions UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Optimization tab judge-facing and allow assumptions to be edited and reapplied from that tab.

**Architecture:** Keep `App.tsx` as the state owner for assumptions, active source, upload file, loading, and rerun behavior. Extend `Optimization.tsx` with editable controls, an apply action, and clearer decision-copy blocks without adding comparison views.

**Tech Stack:** React 19, TypeScript, Vite, Tailwind CSS, lucide-react, Recharts, FastAPI analysis endpoints.

---

### Task 1: Add Optimization Component Contract Coverage

**Files:**
- Create: `kinetic-precision/src/components/Optimization.contract.test.tsx`
- Modify: `kinetic-precision/src/components/Optimization.tsx`

- [ ] **Step 1: Write the failing TypeScript contract test**

Create `kinetic-precision/src/components/Optimization.contract.test.tsx` with JSX that renders `Optimization` using editable assumption props:

```tsx
import { Optimization } from './Optimization';
import { DEFAULT_ASSUMPTIONS, type PlanningAssumptions } from '../lib/api';

const updateAssumptions = (_assumptions: PlanningAssumptions) => {};
const applyAssumptions = () => {};

export const optimizationContract = (
  <Optimization
    analysis={null}
    loading={false}
    loadingStep="upload"
    error={null}
    assumptions={DEFAULT_ASSUMPTIONS}
    onAssumptionsChange={updateAssumptions}
    onApplyAssumptions={applyAssumptions}
    canApplyAssumptions={false}
  />
);
```

- [ ] **Step 2: Run the contract check and confirm it fails**

Run: `npm.cmd run lint`

Expected: TypeScript fails because `OptimizationProps` does not accept the new editable-assumption props.

- [ ] **Step 3: Extend the component props and implementation**

Update `Optimization.tsx` so the component accepts:

```ts
assumptions: PlanningAssumptions;
onAssumptionsChange: (assumptions: PlanningAssumptions) => void;
onApplyAssumptions: () => void;
canApplyAssumptions: boolean;
```

Add editable inputs, Apply button, judge-facing copy blocks, and friendlier peak-planning language.

- [ ] **Step 4: Run the contract check and confirm it passes**

Run: `npm.cmd run lint`

Expected: TypeScript exits with code 0.

### Task 2: Wire App-Level Rerun Behavior

**Files:**
- Modify: `kinetic-precision/src/App.tsx`

- [ ] **Step 1: Track uploaded file state**

Add a `uploadedFile` state. When a user uploads a workbook, store the `File` so the Optimization tab can rerun that upload with changed assumptions.

- [ ] **Step 2: Add an apply callback**

Add `applyAssumptionsFromOptimization()` that reruns the active upload if `uploadedFile` exists, otherwise reruns the selected bundled source file.

- [ ] **Step 3: Pass editable props into Optimization**

Pass `assumptions`, `setAssumptions`, `applyAssumptionsFromOptimization`, and `canApplyAssumptions` to `Optimization`.

- [ ] **Step 4: Run TypeScript verification**

Run: `npm.cmd run lint`

Expected: TypeScript exits with code 0.

### Task 3: Update Required Project Documentation

**Files:**
- Modify: `PROJECT_REQUIREMENTS.md`
- Modify: `ARCHITECTURE_AND_CODING_DESIGN.md`
- Modify: `PROJECT_STATUS.md`

- [ ] **Step 1: Update requirements**

Record that Optimization assumptions must be editable from the Optimization tab and should keep judge-facing wording.

- [ ] **Step 2: Update architecture**

Record that `App.tsx` owns active analysis reruns and passes editable assumptions into Optimization.

- [ ] **Step 3: Update status**

Record completion and verification status for the UI change.

### Task 4: Final Verification

**Files:**
- Verify frontend and documentation changes.

- [ ] **Step 1: Run frontend build**

Run: `npm.cmd run build`

Expected: Vite production build exits with code 0. The known chunk-size warning may remain.

