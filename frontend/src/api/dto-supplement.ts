// DTO supplement — models NOT reachable from the OpenAPI dump (SPEC-400 §5).
//
// CURRENT STATE: EMPTY — fully converged. The M5 companion ticket (#80)
// wired the observation routes' response_model into OpenAPI, so all wire
// models are generated in schema.gen.ts; this supplement's 17 entries were
// deleted per the shrink-only discipline (SPEC-400 §7.1).
//
// The mechanism STAYS: when a future backend surface is added without its
// response_model (an OpenAPI gap), hand-write ONLY the unreachable models
// here with a leading comment naming the shape authority (the Pydantic DTO
// file / SPEC section). scripts/check-dto-supplement.mjs fails CI with the
// exact names to delete the moment a gap closes (npm run dto:check).
// Field names are snake_case verbatim — never rename for style.
