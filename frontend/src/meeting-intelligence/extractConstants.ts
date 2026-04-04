/**
 * Vision Execution — external extract-meeting: max transcript body (characters) for a single API call.
 * Leaves headroom for the fixed prompt (~3–5k chars), workspace mirror, JSON output, and model context limits
 * (typical cloud chat models ≈ 128k tokens; ~92k chars ≈ ~23k tokens transcript + margin).
 */
export const EXTERNAL_EXTRACT_SINGLE_CALL_MAX_CHARS = 92_000
