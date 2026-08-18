/**
 * F4: the core-pin / delegation authorization editor (plan D-043/D-044).
 *
 * F0 explicitly called out the OLD `/parting-line-v2` experimental tab's
 * "fully-built authorization UI... sits on an isolated debug tab, wired to
 * nothing else" as a finding, and F4's instructions say not to recreate
 * that raw-JSON editor blindly. This is a structured, field-level form --
 * each committed entry is validated into the EXACT backend contract shape
 * (`CorePinFaceRefInput`/`DelegationInput`, `src/api/types.ts`, mirroring
 * `_parse_core_pin_face_refs`/`_parse_delegations` in
 * `backend/api/main.py`) before it's added to shared state, so what's in
 * the store is always ready to JSON-stringify and send -- never a partial
 * or malformed draft.
 */

import { useState } from 'react';
import { runManualAnalysis } from '../../../analysis/runManualAnalysis';
import { useAnalysisStore } from '../../../store/analysisStore';
import styles from './AuthorizationEditor.module.css';

function toTuple3(text: [string, string, string]): [number, number, number] {
  return [Number(text[0]), Number(text[1]), Number(text[2])];
}

function parseFaceIdList(text: string): number[] | null {
  const parts = text
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  if (parts.length === 0) return null;
  const ids = parts.map((p) => Number(p));
  return ids.every((n) => Number.isFinite(n) && Number.isInteger(n)) ? ids : null;
}

interface VectorFieldsProps {
  /** Distinguishes this instance's `aria-label`s -- this component is used
   * twice within `AuthorizationEditor` (core-pin axis, delegation movement
   * direction), and identical labels would make both ambiguous to query. */
  labelPrefix: string;
  value: [string, string, string];
  onChange: (value: [string, string, string]) => void;
}

function VectorFields({ labelPrefix, value, onChange }: VectorFieldsProps) {
  return (
    <div className={styles.vectorRow}>
      {(['x', 'y', 'z'] as const).map((axis, i) => (
        <input
          key={axis}
          type="text"
          inputMode="decimal"
          aria-label={`${labelPrefix} ${axis.toUpperCase()} component`}
          className={styles.vectorInput}
          value={value[i]}
          onChange={(e) => {
            const next = [...value] as [string, string, string];
            next[i] = e.target.value;
            onChange(next);
          }}
        />
      ))}
    </div>
  );
}

/**
 * F8: byte-identical to Streamlit's "Load Part3 +Z reference example
 * (candidate 110)" button (`frontend/app.py`, `pv2_load_example`) -- the
 * one known-good authorization example the reference UI ships, not a newly
 * invented one. Only meaningful against Part3.stp at +Z; loading it against
 * a different part/direction is still valid JSON, just not necessarily
 * geometrically applicable.
 */
const REFERENCE_EXAMPLE = {
  corePinFaceRefs: [
    { face_id: 35, axis_direction: [0, 0, 1] as [number, number, number], reason: 'straight coaxial through-bore' },
  ],
  delegations: [
    {
      face_ids: Array.from({ length: 17 }, (_, i) => i), // 0..16
      movement_direction: [1, 0, 0] as [number, number, number],
      movement_type: 'radial_slide',
      source: 'manual_engineering',
      note: 'original rib stack, radial outward +X',
    },
    {
      face_ids: Array.from({ length: 17 }, (_, i) => i + 18), // 18..34
      movement_direction: [-1, 0, 0] as [number, number, number],
      movement_type: 'radial_slide',
      source: 'manual_engineering',
      note: 'mirror rib stack, radial outward -X',
    },
  ],
};

export function AuthorizationEditor() {
  const corePinFaceRefs = useAnalysisStore((s) => s.corePinFaceRefs);
  const delegations = useAnalysisStore((s) => s.delegations);
  const addCorePinFaceRef = useAnalysisStore((s) => s.addCorePinFaceRef);
  const removeCorePinFaceRef = useAnalysisStore((s) => s.removeCorePinFaceRef);
  const addDelegation = useAnalysisStore((s) => s.addDelegation);
  const removeDelegation = useAnalysisStore((s) => s.removeDelegation);
  const clearAuthorization = useAnalysisStore((s) => s.clearAuthorization);
  const manualPullDirection = useAnalysisStore((s) => s.manualPullDirection);
  const selectedFaceIds = useAnalysisStore((s) => s.selectedFaceIds);
  const currentPart = useAnalysisStore((s) => s.currentPart);
  const pullDirection = useAnalysisStore((s) => s.pullDirection);
  const pipelineStatus = useAnalysisStore((s) => s.pipelineStatus);

  const loadReferenceExample = () => {
    clearAuthorization();
    REFERENCE_EXAMPLE.corePinFaceRefs.forEach(addCorePinFaceRef);
    REFERENCE_EXAMPLE.delegations.forEach(addDelegation);
  };

  // F11 §3: the reference example is calibrated for +Z specifically -- the
  // automatic optimizer is free to (and, on Part3, typically does) resolve
  // a DIFFERENT direction where no authorization was ever needed, since
  // `/parting-line-v2` never imports or depends on the direction optimizer
  // (backend-enforced). Rather than silently substituting +Z anywhere, this
  // is a separate, explicitly-labeled action: it runs the full core-cavity
  // pipeline at the literal (0,0,1) vector with whatever authorization is
  // currently configured, so the relationship ("+Z becomes feasible only
  // WITH this authorization") is visible, not assumed.
  const isRunning = pipelineStatus === 'running';
  const directionIsZ = pullDirection ? pullDirection[0] === 0 && pullDirection[1] === 0 && pullDirection[2] === 1 : false;

  const [pinFaceId, setPinFaceId] = useState('');
  const [pinAxis, setPinAxis] = useState<[string, string, string]>(
    manualPullDirection.map(String) as [string, string, string],
  );
  const [pinReason, setPinReason] = useState('');

  const [delFaceIds, setDelFaceIds] = useState('');
  const [delDirection, setDelDirection] = useState<[string, string, string]>(['0', '0', '0']);
  const [delType, setDelType] = useState('radial_slide');
  const [delSource, setDelSource] = useState('manual_engineering');
  const [delNote, setDelNote] = useState('');

  const parsedPinAxis = toTuple3(pinAxis);
  const canAddPin =
    pinFaceId.trim() !== '' &&
    Number.isInteger(Number(pinFaceId)) &&
    parsedPinAxis.every(Number.isFinite) &&
    pinReason.trim() !== '';

  const parsedDelFaceIds = parseFaceIdList(delFaceIds);
  const parsedDelDirection = toTuple3(delDirection);
  const canAddDelegation =
    parsedDelFaceIds !== null &&
    parsedDelDirection.every(Number.isFinite) &&
    delType.trim() !== '' &&
    delSource.trim() !== '' &&
    delNote.trim() !== '';

  return (
    <div className={styles.editor} data-testid="authorization-editor">
      <div className={styles.fieldRow}>
        <button
          type="button"
          className={styles.useSelectedButton}
          onClick={loadReferenceExample}
          title="Loads the same known-good example the Streamlit reference UI ships -- only geometrically meaningful against Part3.stp at +Z (candidate 110)."
        >
          Load Part3 +Z reference example (candidate 110)
        </button>
        <button type="button" className={styles.useSelectedButton} onClick={clearAuthorization}>
          Clear authorization
        </button>
      </div>

      {(corePinFaceRefs.length > 0 || delegations.length > 0) && (
        <div className={styles.section}>
          <p className={styles.sectionHint}>
            This is an ENGINEER-SUPPLIED reference example, not a discovered or automatic result. It is
            geometrically meaningful for Part3.stp specifically at pull direction +Z (0, 0, 1) -- the automatic
            optimizer is free to resolve a different direction where no authorization is needed at all; that is
            expected, not a bug. Use the button below to demonstrate the +Z case directly, independent of whatever
            direction "Run Full Analysis" resolved.
          </p>
          <button
            type="button"
            className={styles.useSelectedButton}
            disabled={!currentPart || isRunning}
            onClick={() => void runManualAnalysis([0, 0, 1], corePinFaceRefs, delegations)}
            title="Runs the full core/cavity pipeline at the literal +Z direction with the current authorization -- separate from the automatic optimizer's own recommended direction."
          >
            Try +Z With This Authorization
          </button>
          {pullDirection && !directionIsZ && (
            <p className={styles.sectionHint}>
              Current resolved direction is ({pullDirection.map((v) => v.toFixed(2)).join(', ')}), not +Z --
              "Continue Analysis with This Authorization" above re-runs at THAT direction; use "Try +Z" here to
              specifically reproduce the +Z / candidate-110 case.
            </p>
          )}
        </div>
      )}

      <section className={styles.section}>
        <h4 className={styles.sectionTitle}>Core-pin face references</h4>
        <p className={styles.sectionHint}>
          Declares a face as a straight coaxial feature the tooling core-pins through, so it is
          excluded from the parting-line search rather than treated as an obstruction.
        </p>

        {corePinFaceRefs.length > 0 && (
          <ul className={styles.entryList} data-testid="core-pin-list">
            {corePinFaceRefs.map((ref, i) => (
              <li key={i} className={styles.entryRow}>
                <span className={styles.entryText}>
                  Face {ref.face_id} — axis ({ref.axis_direction.map((v) => v.toFixed(2)).join(', ')}) —{' '}
                  {ref.reason}
                </span>
                <button
                  type="button"
                  className={styles.removeButton}
                  aria-label={`Remove core-pin face reference for face ${ref.face_id}`}
                  onClick={() => removeCorePinFaceRef(i)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className={styles.addForm}>
          <div className={styles.fieldRow}>
            <label className={styles.fieldLabel}>
              Face ID
              <input
                type="text"
                inputMode="numeric"
                className={styles.textInput}
                value={pinFaceId}
                onChange={(e) => setPinFaceId(e.target.value)}
                placeholder={selectedFaceIds[0]?.toString() ?? 'e.g. 35'}
              />
            </label>
            <button
              type="button"
              className={styles.useSelectedButton}
              disabled={selectedFaceIds.length !== 1}
              onClick={() => setPinFaceId(String(selectedFaceIds[0]))}
            >
              Use selected face
            </button>
          </div>
          <label className={styles.fieldLabel}>
            Axis direction
            <VectorFields labelPrefix="Core-pin axis" value={pinAxis} onChange={setPinAxis} />
          </label>
          <label className={styles.fieldLabel}>
            Reason
            <input
              type="text"
              className={styles.textInput}
              value={pinReason}
              onChange={(e) => setPinReason(e.target.value)}
              placeholder="e.g. straight coaxial through-bore"
            />
          </label>
          <button
            type="button"
            className={styles.addButton}
            disabled={!canAddPin}
            onClick={() => {
              addCorePinFaceRef({
                face_id: Number(pinFaceId),
                axis_direction: parsedPinAxis,
                reason: pinReason.trim(),
              });
              setPinFaceId('');
              setPinAxis(manualPullDirection.map(String) as [string, string, string]);
              setPinReason('');
            }}
          >
            Add core-pin reference
          </button>
        </div>
      </section>

      <section className={styles.section}>
        <h4 className={styles.sectionTitle}>Delegated secondary actions</h4>
        <p className={styles.sectionHint}>
          Declares that a group of faces is handled by a separate tooling mechanism (a side action,
          e.g. a slide or lifter) moving along its own direction, so H4 excludes them from the main
          parting-line's orientation-area sums.
        </p>

        {delegations.length > 0 && (
          <ul className={styles.entryList} data-testid="delegation-list">
            {delegations.map((d, i) => (
              <li key={i} className={styles.entryRow}>
                <span className={styles.entryText}>
                  Faces {'{'}
                  {d.face_ids.join(', ')}
                  {'}'} → {d.movement_type} ({d.movement_direction.map((v) => v.toFixed(2)).join(', ')}) —{' '}
                  {d.note}
                </span>
                <button
                  type="button"
                  className={styles.removeButton}
                  aria-label={`Remove delegation for faces ${d.face_ids.join(', ')}`}
                  onClick={() => removeDelegation(i)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className={styles.addForm}>
          <label className={styles.fieldLabel}>
            Face IDs (comma-separated)
            <input
              type="text"
              className={styles.textInput}
              value={delFaceIds}
              onChange={(e) => setDelFaceIds(e.target.value)}
              placeholder="e.g. 0,1,2,3,4"
            />
          </label>
          <label className={styles.fieldLabel}>
            Movement direction
            <VectorFields labelPrefix="Delegation movement direction" value={delDirection} onChange={setDelDirection} />
          </label>
          <div className={styles.fieldRow}>
            <label className={styles.fieldLabel}>
              Movement type
              <input
                type="text"
                className={styles.textInput}
                value={delType}
                onChange={(e) => setDelType(e.target.value)}
              />
            </label>
            <label className={styles.fieldLabel}>
              Source
              <input
                type="text"
                className={styles.textInput}
                value={delSource}
                onChange={(e) => setDelSource(e.target.value)}
              />
            </label>
          </div>
          <label className={styles.fieldLabel}>
            Note
            <input
              type="text"
              className={styles.textInput}
              value={delNote}
              onChange={(e) => setDelNote(e.target.value)}
              placeholder="e.g. original rib stack, radial outward +X"
            />
          </label>
          <button
            type="button"
            className={styles.addButton}
            disabled={!canAddDelegation}
            onClick={() => {
              addDelegation({
                face_ids: parsedDelFaceIds as number[],
                movement_direction: parsedDelDirection,
                movement_type: delType.trim(),
                source: delSource.trim(),
                note: delNote.trim(),
              });
              setDelFaceIds('');
              setDelDirection(['0', '0', '0']);
              setDelNote('');
            }}
          >
            Add delegation
          </button>
        </div>
      </section>
    </div>
  );
}
