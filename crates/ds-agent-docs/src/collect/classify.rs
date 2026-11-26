//! Record classification for the session collector.
//!
//! Port of the Python collector's record helpers: correction detection, human
//! evidence extraction, tool-error extraction, headless detection, record
//! recognition, stable message ids and the drift threshold.

use std::sync::OnceLock;

use regex::Regex;
use serde_json::{Map, Value};

use super::{Session, SessionInput};
use crate::redact::redact;
use crate::repo::sha256_hex;

/// Opening line of an implementer prompt: such a session is the tool's own.
pub const IMPLEMENTER_OPENING: &str = "You are the implementer for one step of a plan";

/// Roles that carry human-authored text.
pub const HUMAN_ROLES: [&str; 3] = ["user", "human", "user_message"];

/// Markers that identify this tool's own session, current and legacy.
const SELF_SESSION_MARKERS: [&str; 2] = [
    "<!-- ds-agent-docs:self-session -->",
    "<!-- backpass:self-session -->",
];

/// Injected boilerplate that is never human evidence.
const NOISE_PREFIXES: [&str; 7] = [
    "<task-notification",
    "Stop hook feedback",
    "<user-prompt-submit-hook>",
    "This session is being continued from a previous",
    "Base directory for this skill:",
    "Caveat: The messages below",
    "# Handoff:",
];

fn noise() -> &'static Regex {
    static NOISE: OnceLock<Regex> = OnceLock::new();
    NOISE.get_or_init(|| {
        Regex::new(
            r"(?i)^\s*<(system-reminder|command-|local-command|user_instructions|environment_context)",
        )
        .expect("noise pattern must compile")
    })
}

fn pasted() -> &'static Regex {
    static PASTED: OnceLock<Regex> = OnceLock::new();
    PASTED.get_or_init(|| {
        Regex::new(r"(?s)<pasted_content[^>]*>.*?(?:</pasted_content>|\z)")
            .expect("pasted pattern must compile")
    })
}

fn fenced_code() -> &'static Regex {
    static FENCED: OnceLock<Regex> = OnceLock::new();
    FENCED.get_or_init(|| {
        Regex::new(r"(?s)```.*?```|~~~.*?~~~").expect("fenced-code pattern must compile")
    })
}

fn inline_code() -> &'static Regex {
    static INLINE: OnceLock<Regex> = OnceLock::new();
    INLINE.get_or_init(|| Regex::new(r"`[^`]*`").expect("inline-code pattern must compile"))
}

fn sentence_start() -> &'static Regex {
    static START: OnceLock<Regex> = OnceLock::new();
    START.get_or_init(|| {
        Regex::new(
            r"(?i)^(?:no|nope)\s*[,.;:!\-]|^wrong\b|^incorrect\b|^stop\b|^don'?t\b|^do not\b|^never\b",
        )
        .expect("sentence-start pattern must compile")
    })
}

fn anywhere() -> &'static Regex {
    static ANYWHERE: OnceLock<Regex> = OnceLock::new();
    ANYWHERE.get_or_init(|| {
        Regex::new(
            r"(?i)that'?s wrong|not like that|i told you|i said|you should have|you shouldn'?t|you forgot|you missed|you broke|instead of|\binstead\s*[.!]?$",
        )
        .expect("anywhere pattern must compile")
    })
}

/// Python truthiness for a JSON value: null, `false`, `0`, `""` and empty
/// containers are false.
pub(crate) fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(flag) => *flag,
        Value::Number(number) => number.as_f64().is_some_and(|value| value != 0.0),
        Value::String(text) => !text.is_empty(),
        Value::Array(items) => !items.is_empty(),
        Value::Object(map) => !map.is_empty(),
    }
}

/// Treat a JSON `null` like a missing key.
pub(crate) fn non_null(value: Option<&Value>) -> Option<&Value> {
    value.filter(|item| !item.is_null())
}

/// The payload-carrying node of a record and its message object, if any.
pub fn record_parts(record: &Value) -> (&Value, Option<&Map<String, Value>>) {
    let node = match record.get("payload") {
        Some(payload) if payload.is_object() => payload,
        _ => record,
    };
    let message = node.get("message").and_then(Value::as_object);
    (node, message)
}

/// First truthy role-like value: message role, then node role/type, then record type.
pub fn record_role(record: &Value) -> Option<&Value> {
    let (node, message) = record_parts(record);
    let mut candidates: Vec<Option<&Value>> = Vec::new();
    if let Some(message) = message {
        candidates.push(message.get("role"));
    }
    candidates.push(node.get("role"));
    candidates.push(node.get("type"));
    candidates.push(record.get("type"));
    candidates.into_iter().flatten().find(|value| truthy(value))
}

/// First object among the record, its node and its message that holds `key`.
pub fn field<'a>(record: &'a Value, key: &str) -> Option<&'a Value> {
    let (node, message) = record_parts(record);
    if let Some(value) = record.get(key) {
        return Some(value);
    }
    if let Some(value) = node.get(key) {
        return Some(value);
    }
    message.and_then(|map| map.get(key))
}

/// Python's missing-key default for the `content`/`parts`/`text` fallbacks.
fn content_chain(map: &Map<String, Value>) -> Option<&Value> {
    map.get("content")
        .or_else(|| map.get("parts"))
        .or_else(|| map.get("text"))
}

/// String kind carried by an origin-like value (string or `{kind|type}` object).
pub fn origin_kind(value: Option<&Value>) -> Option<&str> {
    match value {
        Some(Value::Object(map)) => {
            let inner = match map.get("kind") {
                Some(inner) => Some(inner),
                None => map.get("type"),
            };
            inner.and_then(Value::as_str)
        }
        Some(Value::String(text)) => Some(text.as_str()),
        _ => None,
    }
}

/// Flatten a message `content` value into text.
pub fn text_of(content: Option<&Value>) -> String {
    match content {
        Some(Value::String(text)) => text.clone(),
        Some(Value::Array(items)) => {
            let mut parts: Vec<&str> = Vec::new();
            for item in items {
                match item {
                    Value::String(text) => parts.push(text.as_str()),
                    Value::Object(map) => {
                        let kind_allowed = match map.get("type") {
                            None | Some(Value::Null) => true,
                            Some(Value::String(kind)) => kind == "text" || kind == "input_text",
                            _ => false,
                        };
                        if kind_allowed && let Some(Value::String(text)) = map.get("text") {
                            parts.push(text.as_str());
                        }
                    }
                    _ => {}
                }
            }
            parts.join("\n")
        }
        Some(Value::Object(map)) => {
            let inner = ["content", "text", "parts"]
                .iter()
                .filter_map(|key| map.get(*key))
                .find(|value| truthy(value));
            text_of(inner)
        }
        _ => String::new(),
    }
}

/// Working directory a record was written in, looking through `payload`.
pub fn find_cwd(record: &Value) -> Option<String> {
    for key in ["cwd", "workdir", "projectRoot", "project_root"] {
        if let Some(Value::String(value)) = record.get(key) {
            return Some(value.clone());
        }
    }
    match record.get("payload") {
        Some(payload) if payload.is_object() => find_cwd(payload),
        _ => None,
    }
}

/// Drop `<pasted_content>` spans, including an unterminated trailing one.
pub fn remove_pasted(text: &str) -> String {
    pasted().replace_all(text, "").into_owned()
}

/// True when `text` is injected boilerplate rather than a person's words.
pub fn is_noise_text(text: &str) -> bool {
    noise().is_match(text) || NOISE_PREFIXES.iter().any(|prefix| text.starts_with(prefix))
}

/// True when the record belongs to a session this tool itself started.
pub fn is_self_session(text: &str) -> bool {
    let text = text.trim_start();
    SELF_SESSION_MARKERS
        .iter()
        .any(|marker| text.starts_with(marker))
}

/// The unstripped text a human-role record carries.
pub fn user_raw_text(record: &Value) -> String {
    let (node, message) = record_parts(record);
    let content = non_null(message.and_then(content_chain)).or_else(|| {
        non_null(
            node.get("content")
                .or_else(|| node.get("parts"))
                .or_else(|| node.get("text")),
        )
    });
    let mut text = text_of(content);
    if text.is_empty()
        && let Some(Value::String(message)) = node.get("message")
    {
        text = message.clone();
    }
    text
}

/// Human-authored text of a record, or `None` when it is not human evidence.
pub fn human_text(record: &Value) -> Option<String> {
    let role = record_role(record).and_then(Value::as_str)?;
    if !HUMAN_ROLES.contains(&role) {
        return None;
    }
    for key in ["isMeta", "isSidechain", "isCompactSummary"] {
        if field(record, key).is_some_and(truthy) {
            return None;
        }
    }
    if let Some(kind) = origin_kind(field(record, "origin"))
        && kind != "human"
    {
        return None;
    }
    if let Some(turn) = origin_kind(field(record, "turnOrigin"))
        && turn != "human"
    {
        return None;
    }
    if let Some(Value::String(entrypoint)) = field(record, "entrypoint")
        && entrypoint.starts_with("sdk")
    {
        return None;
    }
    if let Some(value) = non_null(field(record, "promptSource"))
        && !matches!(value, Value::String(text) if text == "typed")
    {
        return None;
    }
    if let Some(Value::String(kind)) = field(record, "sessionKind")
        && kind.to_lowercase() == "bg"
    {
        return None;
    }
    if let Some(value) = non_null(field(record, "userType"))
        && !matches!(value, Value::String(text) if text == "external")
    {
        return None;
    }
    let (node, message) = record_parts(record);
    let content = non_null(message.and_then(content_chain)).or_else(|| {
        non_null(
            node.get("content")
                .or_else(|| node.get("parts"))
                .or_else(|| node.get("text")),
        )
    });
    if let Some(Value::Array(blocks)) = content {
        for block in blocks {
            if block.get("type").and_then(Value::as_str) == Some("tool_result") {
                return None;
            }
        }
    }
    let mut text = text_of(content);
    if text.is_empty()
        && let Some(Value::String(message)) = node.get("message")
    {
        text = message.clone();
    }
    let text = remove_pasted(&text).trim().to_string();
    if text.is_empty() || is_noise_text(&text) {
        return None;
    }
    Some(text)
}

fn id_from(map: &Map<String, Value>) -> Option<String> {
    for key in ["uuid", "messageId", "message_id", "id"] {
        if let Some(Value::String(value)) = map.get(key)
            && !value.is_empty()
        {
            return Some(value.clone());
        }
    }
    None
}

/// Stable id for a human message: the record's own id, else a text hash.
pub fn message_id(record: &Value, text: &str) -> String {
    let (node, message) = record_parts(record);
    if let Value::Object(map) = record
        && let Some(id) = id_from(map)
    {
        return id;
    }
    if let Value::Object(map) = node
        && let Some(id) = id_from(map)
    {
        return id;
    }
    if let Some(map) = message
        && let Some(id) = id_from(map)
    {
        return id;
    }
    sha256_hex(text).chars().take(16).collect()
}

fn python_zero(value: &Value) -> bool {
    match value {
        Value::Null => true,
        Value::Bool(flag) => !flag,
        Value::Number(number) => number.as_f64().is_some_and(|value| value == 0.0),
        _ => false,
    }
}

/// Tool-error texts carried by a record.
pub fn error_texts(record: &Value) -> Vec<String> {
    let (node, message) = record_parts(record);
    let mut out: Vec<String> = Vec::new();
    let content = non_null(message.and_then(|map| map.get("content")))
        .or_else(|| non_null(node.get("content")));
    if let Some(Value::Array(blocks)) = content {
        for block in blocks {
            let is_tool_result = block.get("type").and_then(Value::as_str) == Some("tool_result");
            if is_tool_result && block.get("is_error").is_some_and(truthy) {
                out.push(text_of(block.get("content")));
            }
        }
    }
    if matches!(
        node.get("type").and_then(Value::as_str),
        Some("function_call_output" | "exec_command_end")
    ) {
        let output = match node.get("output") {
            Some(value) if value.is_object() => value,
            _ => node,
        };
        let failed = match output.get("exit_code") {
            None => false,
            Some(code) => !python_zero(code),
        };
        if failed {
            let detail = ["output", "stderr"]
                .iter()
                .filter_map(|key| output.get(*key))
                .find(|value| truthy(value));
            out.push(text_of(detail));
        }
    }
    out.retain(|text| !text.is_empty());
    out
}

/// True when the record comes from a non-interactive (SDK/background) session.
pub fn is_headless(record: &Value) -> bool {
    if let Some(Value::String(entrypoint)) = field(record, "entrypoint")
        && entrypoint.starts_with("sdk")
    {
        return true;
    }
    matches!(
        field(record, "sessionKind"),
        Some(Value::String(kind)) if kind.to_lowercase() == "bg"
    )
}

fn well_formed_message(node: &Value, message: Option<&Map<String, Value>>) -> bool {
    if let Some(map) = message
        && ["content", "parts", "text"]
            .iter()
            .any(|key| map.contains_key(*key))
    {
        return true;
    }
    if let Some(Value::String(text)) = node.get("message")
        && !text.trim().is_empty()
    {
        return true;
    }
    if matches!(
        node.get("content"),
        Some(Value::String(_) | Value::Array(_))
    ) {
        return true;
    }
    matches!(node.get("text"), Some(Value::String(_)))
}

/// `(recognized, is_well_formed_user_message)` for one transcript record.
pub fn recognized_record(record: &Value) -> (bool, bool) {
    if !record.is_object() {
        return (false, false);
    }
    let typed = record.get("type").is_some_and(Value::is_string)
        || record.get("role").is_some_and(Value::is_string);
    if !typed {
        return (false, false);
    }
    let (node, message) = record_parts(record);
    let role = record_role(record).and_then(Value::as_str);
    match role {
        Some(role) if HUMAN_ROLES.contains(&role) || role == "assistant" => {
            let well_formed = well_formed_message(node, message);
            (well_formed, well_formed && HUMAN_ROLES.contains(&role))
        }
        _ => (true, false),
    }
}

/// Assemble a session record, applying redaction and the empty-evidence exclusion.
pub fn make_session(input: SessionInput) -> Session {
    let mut excluded = input.excluded;
    if input.human.is_empty() && input.errors.is_empty() {
        excluded = true;
    }
    let mtime = if input.mtime.is_finite() {
        input.mtime
    } else {
        0.0
    };
    let label = redact(&input.label);
    let group = input
        .group
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| label.clone());
    Session {
        id: format!("{}:{}", input.source, label),
        source: input.source,
        label,
        mtime,
        headless: input.headless,
        group: redact(&group),
        human: input.human,
        errors: input
            .errors
            .iter()
            .filter(|error| !error.is_empty())
            .map(|error| redact(error))
            .collect(),
        excluded,
    }
}

/// Name of the source whose transcripts drifted, when the threshold is crossed.
pub fn drift_source(source: &str, stats: &super::ScanStats) -> Option<String> {
    if stats.total >= 20 && (stats.recognized * 2 < stats.total || !stats.user_ok) {
        return Some(source.to_string());
    }
    None
}

/// Split on sentence boundaries the way the Python lookbehind splitter does:
/// whitespace after `.`, `!` or `?`, or a run of newlines.
fn split_sentences(text: &str) -> Vec<&str> {
    let chars: Vec<(usize, char)> = text.char_indices().collect();
    let mut out: Vec<&str> = Vec::new();
    let mut start = 0usize;
    let mut index = 0usize;
    while index < chars.len() {
        let (position, letter) = chars[index];
        if matches!(letter, '.' | '!' | '?') {
            let mut next = index + 1;
            while next < chars.len() && chars[next].1.is_whitespace() {
                next += 1;
            }
            if next > index + 1 {
                out.push(&text[start..position + letter.len_utf8()]);
                start = chars.get(next).map_or(text.len(), |(offset, _)| *offset);
                index = next;
                continue;
            }
        } else if letter == '\n' {
            let mut next = index + 1;
            while next < chars.len() && chars[next].1 == '\n' {
                next += 1;
            }
            out.push(&text[start..position]);
            start = chars.get(next).map_or(text.len(), |(offset, _)| *offset);
            index = next;
            continue;
        }
        index += 1;
    }
    out.push(&text[start..]);
    out
}

/// True when a human message reads as a correction of the agent's work.
pub fn is_correction(text: &str) -> bool {
    if text.trim().is_empty() {
        return false;
    }
    let cleaned = fenced_code().replace_all(text, " ").into_owned();
    let cleaned = inline_code().replace_all(&cleaned, " ").into_owned();
    for raw in split_sentences(&cleaned) {
        let sentence = raw.trim();
        if sentence.is_empty() || sentence.ends_with('?') {
            continue;
        }
        if sentence_start().is_match(sentence) || anywhere().is_match(sentence) {
            return true;
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splits_on_punctuation_whitespace_and_newlines() {
        assert_eq!(split_sentences("a. b! c? d"), vec!["a.", "b!", "c?", "d"]);
        assert_eq!(split_sentences("a\n\nb"), vec!["a", "b"]);
        assert_eq!(split_sentences("a.\n\nb"), vec!["a.", "b"]);
        assert_eq!(split_sentences("a.b"), vec!["a.b"]);
        assert_eq!(split_sentences("a\n \n b"), vec!["a", " ", " b"]);
        assert_eq!(split_sentences(""), vec![""]);
        assert_eq!(split_sentences("a. "), vec!["a.", ""]);
    }

    #[test]
    fn recognizes_corrections_and_ignores_questions() {
        assert!(is_correction("No, use bun here, not npm."));
        assert!(is_correction("don't do that"));
        assert!(!is_correction("Should we add a retry?"));
        assert!(!is_correction("   "));
        // Fenced and inline code never trigger the marker.
        assert!(!is_correction("```\nnever do this\n```"));
        assert!(!is_correction("`don't`"));
    }

    #[test]
    fn message_ids_prefer_record_identifiers() {
        let record = serde_json::json!({"uuid": "abc", "message": {"id": "other"}});
        assert_eq!(message_id(&record, "text"), "abc");
        let bare = serde_json::json!({"type": "user"});
        assert_eq!(message_id(&bare, "text").len(), 16);
    }
}
