# Scholia Cleanup Log
Date: 2026-02-25
Reports: code-simplifier, refactor-cleaner, code-reviewer

## Deletions
| File | Lines | Reason | Commit |
|------|-------|--------|--------|
| `nul` | 73B | Windows artifact | Phase 1 |
| `Usersbharadevscholiatmp_conv.json` | ~33KB | Garbled filename temp file | Phase 1 |
| `C:Usersbharadevscholiatmp_conv.json` | ~33KB | Garbled filename temp file | Phase 1 |
| `C:Usersbharadevscholiabackendservicesrunpod_scriptscoordinator_v4.py` | ~20KB | Garbled filename script | Phase 1 |
| `backend/scholia.db` | 0B | Empty DB; real DB is `data/library.db` | Phase 1 |
| `backend/check_import.py` | ~15 lines | One-off debug script | Phase 1 |
| `backend/check_pods.py` | ~20 lines | One-off RunPod script | Phase 1 |
| `backend/check_ready.py` | ~50 lines | One-off RunPod script | Phase 1 |
| `backend/resume_pod.py` | ~35 lines | One-off RunPod script | Phase 1 |
| `backend/setup_montreal.py` | ~110 lines | One-off RunPod script | Phase 1 |
| `backend/start_pods.py` | ~175 lines | One-off RunPod script | Phase 1 |
| `compare_docs.py` | ~100 lines | Standalone utility, not part of app | Phase 1 |
| `backend/routers/rems.py` | 699 lines | Dead router; gluons router replaced it | Phase 2 |
| `backend/routers/documents.py` | 1,104 lines | Dead router; sources router replaced it | Phase 2 |
| `backend/models/rem.py` | 31 lines | Re-export shim, only imported by itself | Phase 2 |
| `backend/utils/offset_mapper.py` | 169 lines | Zero imports anywhere | Phase 2 |
| `backend/services/lit_engine/pdf_extractor.py` | ~100 lines | Never imported | Phase 2 |
| `frontend/src/components/Reader/ChatTab.jsx` | ~600 lines | Superseded by SimpleChatTab | Phase 2 |
| `frontend/src/components/Research/SourcesPanel.jsx` | ~200 lines | Superseded by SourcesPanelVertical | Phase 2 |
| `frontend/src/components/Research/index.js` | ~10 lines | Unused barrel export | Phase 2 |

## Removals (within files)
| File | What removed | Reason | Commit |
|------|-------------|--------|--------|
| `backend/models/gluon.py:99-105` | Rem backward-compat aliases | Dead code; no consumers | Phase 2 |
| `backend/models/__init__.py:9-10,23` | Rem re-exports from `__all__` | Dead code | Phase 2 |
| `backend/server.py:115` | `/rems` legacy router mount | Dead endpoint | Phase 2 |
| `backend/routers/sources.py:2906` | Duplicate `from pydantic import BaseModel` | Already imported at line 21 | Phase 2 |
| `frontend/src/hooks/useApi.js` | 10 backward-compat aliases | `useDocuments`, `useDocument`, `useImportDocument`, `useUpdateDocument`, `useDocumentGluonStats`, `useDeleteDocument`, `useRefreshDocuments`, `useDocumentContent`, `useDocumentNotes`, `useRemSearch` | Phase 2 |
| `frontend/src/hooks/useApi.js:476` | `useRem` alias | Replaced with direct `useGluon` import in Gluon.jsx | Phase 2 |
| `frontend/src/hooks/useCouncil.js:427-430` | `getModelInfo()` | Not imported anywhere | Phase 2 |
| `frontend/src/hooks/useChat.js:168-171` | `getModelInfo()` | Not imported anywhere | Phase 2 |

## Consolidations
| What | From → To | Commit |
|------|-----------|--------|
| `apiFetch()` | 4 inline copies (useApi, useCouncil, useChat, useRLM) → `frontend/src/utils/api.js` | Phase 3 |
| `formatCost()` | 2 inline copies (useCouncil, useChat) → `frontend/src/utils/api.js` | Phase 3 |

## Security Fixes
| Issue | File | Fix | Commit |
|-------|------|-----|--------|
| Unsandboxed `exec()` | `backend/services/rlm_v2_engine.py:566` | Restrict `__builtins__` to safe subset; blocklist dangerous imports | Phase 4 |
| Bare `except:` | `backend/services/lit_engine/assessor.py:160` | → `except (ValueError, TypeError, KeyError):` | Phase 4 |
| Bare `except:` | `backend/services/runpod_api.py:105` | → `except (ValueError, KeyError):` | Phase 4 |
