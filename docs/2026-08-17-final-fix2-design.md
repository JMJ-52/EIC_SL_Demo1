# Final Re-review Fix 2 Design

## Scope

Resolve the four Important findings in `.sdd/final-rereview.md` without
changing authentication, role routing, persistence, or AI failure semantics.

## Design

An imported runtime registry will own the process-lifetime startup-cleanup
sentinel and the set of active upload-session tokens. Because Streamlit reruns
re-execute the entry script but reuse imported modules, ordinary reruns will not
reset this state. Registration and startup cleanup share one lock. The stale
storage sweep will accept a validated exclusion set and continue to inspect and
delete entries without following symlinks. Startup cleanup will use the normal
stale-age threshold rather than treating every directory as immediately stale.

The general equipment workflow will detect administrator-approved rows and
present them as read-only. This prevents the guest/general editor from crashing
or reversing an administrator lifecycle decision.

Project deletion will collect document paths from the selected project,
prevalidate every physical path against the current session token and storage
root, and only then delete those exact files. Metadata deletion runs only after
the complete prevalidation succeeds, so a foreign, unsafe, or unavailable path
aborts the cascade visibly and preserves project metadata for retry. Sibling
files and other session directories remain untouched.

The AI re-review submit handler will assign the returned `AnalysisOutcome` and
pass that exact object to the existing outcome renderer. Existing exception and
partial-warning behavior remains unchanged.

## Tests

Regression tests will simulate entry-module reloads, confirm that old stale
directories are removed while active and symlinked directories survive, render
an administrator-approved equipment row through the general editor, exercise
successful and rejected project-upload cleanup, and cover successful and
warning-bearing re-review outcomes. The complete suite, compileall, and
standalone application imports are the final acceptance checks.

