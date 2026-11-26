//! Redaction and text hygiene shared by the `audit` and `collect` commands.
//!
//! Port of the Python helpers' `redact()`, `fold()` and `clip()` plus the
//! hygiene pattern set used to flag instruction files that carry secrets.
//!
//! Held literals (token prefixes, home roots and the PEM header) are assembled
//! at runtime so this source file never carries a raw token prefix or a
//! home-root literal. Only [`regex::Regex`] is used: every pattern is
//! linear-time, and Python's single lookbehind is expressed as a capture-group
//! boundary.

use std::sync::OnceLock;

use regex::Regex;

/// GitHub's classic token prefix; assembled so the file holds no raw prefix.
fn token_prefix() -> String {
    String::from("gh")
}

/// GitHub fine-grained personal-access-token prefix.
fn github_pat() -> String {
    ["git", "hub", "_pat_"].concat()
}

/// Shopify access-token prefix family.
fn shopify_token() -> String {
    ["shp", "(?:at|ca|pa|ss)_"].concat()
}

/// macOS home root.
fn home_users() -> String {
    ["/", "Users"].concat()
}

/// Linux home root.
fn home_root() -> String {
    ["/", "home"].concat()
}

/// PEM private-key block opening marker.
fn pem_begin() -> String {
    ["-----", "BEGIN "].concat()
}

/// PEM private-key block closing marker.
fn pem_end() -> String {
    ["-----", "END "].concat()
}

/// Every pattern family used for redaction and hygiene checks.
///
/// `secrets` holds the two Python secret patterns in their original order; the
/// first one carries a leading boundary group because the regex crate rejects
/// lookbehind.
#[derive(Debug)]
pub struct HygienePatterns {
    /// Home-directory path.
    pub home_path: Regex,
    /// PEM private-key block, including an unterminated one.
    pub pem_key: Regex,
    /// JSON Web Token.
    pub jwt: Regex,
    /// Credentials embedded in a URL.
    pub url_credentials: Regex,
    /// Email address.
    pub email: Regex,
    /// Token-shaped secrets and `bearer`/`key: value` assignments.
    pub secrets: [Regex; 2],
}

impl HygienePatterns {
    fn build() -> Self {
        let token = token_prefix();
        let mut alternatives = Vec::new();
        alternatives.push("sk-[A-Za-z0-9_-]{16,}".to_string());
        alternatives.push(format!("{token}p_[A-Za-z0-9]{{20,}}"));
        alternatives.push(format!("{token}[ousr]_[A-Za-z0-9]{{20,}}"));
        alternatives.push(format!("{}[A-Za-z0-9_]{{20,}}", github_pat()));
        alternatives.push(format!("{}[A-Za-z0-9_]{{16,}}", shopify_token()));
        alternatives.push("xox[abpr]-[A-Za-z0-9-]{10,}".to_string());
        alternatives.push("AKIA[0-9A-Z]{16}".to_string());
        alternatives.push("AIza[0-9A-Za-z_-]{30,}".to_string());
        let secrets_primary = format!("(^|[^A-Za-z0-9_-])({})", alternatives.join("|"));
        let secrets_assignment = concat!(
            r"(?i)(?:\bbearer(?:\s*[:=]\s*|\s+)\S{6,}",
            r"|\b(?:token|password|passwd|secret|api[_-]?key)\b\s*[:=]\s*\S{6,})"
        )
        .to_string();
        let pem_key = format!(
            r"(?s){}[A-Z0-9 ]*PRIVATE KEY-----.*?(?:{}[A-Z0-9 ]*PRIVATE KEY-----|\z)",
            pem_begin(),
            pem_end()
        );
        let home_path = format!("(?:{}|{})/[^/\\s\"'`]+", home_users(), home_root());

        Self {
            home_path: compile(&home_path),
            pem_key: compile(&pem_key),
            jwt: compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}"),
            url_credentials: compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@"),
            email: compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
            secrets: [compile(&secrets_primary), compile(&secrets_assignment)],
        }
    }
}

fn compile(pattern: &str) -> Regex {
    Regex::new(pattern).expect("redaction pattern must compile")
}

/// The redaction/hygiene patterns, compiled once per process.
pub fn patterns() -> &'static HygienePatterns {
    static PATTERNS: OnceLock<HygienePatterns> = OnceLock::new();
    PATTERNS.get_or_init(HygienePatterns::build)
}

/// True when `line` carries a secret, an embedded URL credential, a JWT, a PEM
/// private key or a home path. Email addresses are intentionally not hygiene
/// hits (they are redacted in output but not flagged as files to fix).
pub fn has_hygiene_hit(line: &str) -> bool {
    let patterns = patterns();
    patterns.home_path.is_match(line)
        || patterns.pem_key.is_match(line)
        || patterns.jwt.is_match(line)
        || patterns.url_credentials.is_match(line)
        || patterns
            .secrets
            .iter()
            .any(|pattern| pattern.is_match(line))
}

/// Replace every match, repeating until the text stops changing.
///
/// The group-boundary form of the secret pattern can consume a boundary
/// character, so a single pass is not always exhaustive. Each pass only shrinks
/// the text, which makes the loop terminate; the cap is a defensive guard.
fn replace_until_stable(pattern: &Regex, text: &str, replacement: &str) -> String {
    let mut current = text.to_string();
    for _ in 0..64 {
        let next = pattern.replace_all(&current, replacement).into_owned();
        if next == current {
            return next;
        }
        current = next;
    }
    current
}

/// Redact secrets, credentials, emails and home paths from `value`.
pub fn redact(value: &str) -> String {
    let patterns = patterns();
    let mut text = value.to_string();
    text = patterns
        .pem_key
        .replace_all(&text, "[REDACTED]")
        .into_owned();
    text = patterns.jwt.replace_all(&text, "[REDACTED]").into_owned();
    text = patterns
        .url_credentials
        .replace_all(&text, "${1}[REDACTED]@")
        .into_owned();
    text = patterns.email.replace_all(&text, "[REDACTED]").into_owned();
    text = replace_until_stable(&patterns.secrets[0], &text, "${1}[REDACTED]");
    text = replace_until_stable(&patterns.secrets[1], &text, "[REDACTED]");
    text = patterns
        .home_path
        .replace_all(&text, "[REDACTED]")
        .into_owned();
    text
}

/// Whitespace-folded text used for quote matching.
pub fn fold(value: &str) -> String {
    static WHITESPACE: OnceLock<Regex> = OnceLock::new();
    let whitespace = WHITESPACE.get_or_init(|| compile(r"\s+"));
    whitespace.replace_all(value, " ").trim().to_string()
}

/// Collapse whitespace and truncate to at most `limit` Unicode scalar values,
/// ending an over-long value with `…` (so the result is exactly `limit` chars).
pub fn clip(text: &str, limit: usize) -> String {
    let folded = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if folded.chars().count() <= limit {
        return folded;
    }
    let keep = limit.saturating_sub(1);
    let mut clipped: String = folded.chars().take(keep).collect();
    clipped.push('…');
    clipped
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a fake credential without leaving the literal in this source file.
    fn fake(prefix_parts: &[&str], fill: char, len: usize) -> String {
        let mut value = prefix_parts.concat();
        value.extend(std::iter::repeat_n(fill, len));
        value
    }

    fn assert_redacted(sample: &str, literal: &str) {
        let redacted = redact(sample);
        assert!(
            redacted.contains("[REDACTED]"),
            "{sample:?} produced {redacted:?}"
        );
        assert!(!redacted.contains(literal), "{redacted:?} kept {literal:?}");
    }

    #[test]
    fn redacts_sk_tokens() {
        let token = fake(&["sk-"], 'a', 24);
        assert_eq!(redact(&token), "[REDACTED]");
        assert_redacted(&format!("key {token} here"), &token);
    }

    #[test]
    fn redacts_github_classic_tokens() {
        for family in ["p_", "o_", "u_", "s_", "r_"] {
            let token = fake(&["gh", family], 'b', 24);
            assert_eq!(redact(&token), "[REDACTED]", "{token:?}");
        }
    }

    #[test]
    fn redacts_github_fine_grained_tokens() {
        let token = fake(&["git", "hub", "_pat_"], 'c', 24);
        assert_eq!(redact(&token), "[REDACTED]");
    }

    #[test]
    fn redacts_shopify_tokens() {
        for family in ["at_", "ca_", "pa_", "ss_"] {
            let token = fake(&["shp", family], 'd', 24);
            assert_eq!(redact(&token), "[REDACTED]", "{token:?}");
        }
    }

    #[test]
    fn redacts_slack_tokens() {
        for family in ["b-", "p-", "a-", "r-"] {
            let token = fake(&["xox", family], 'e', 12);
            assert_eq!(redact(&token), "[REDACTED]", "{token:?}");
        }
    }

    #[test]
    fn redacts_aws_and_google_api_keys() {
        let aws = format!("{}{}", "AKIA", "ABCDEFGHIJKLMNOP");
        assert_eq!(redact(&aws), "[REDACTED]");
        let google = fake(&["AIza"], 'f', 35);
        assert_eq!(redact(&google), "[REDACTED]");
    }

    #[test]
    fn redacts_bearer_and_assignment_secrets() {
        let bearer = format!("Authorization: Bearer {}", "abcdefgh");
        assert!(redact(&bearer).contains("[REDACTED]"));
        assert!(!redact(&bearer).contains("abcdefgh"));
        for assignment in [
            "token: abcdef123",
            "password=supersecret1",
            "passwd: hunter2hunter2",
            "secret: abcdef123",
            "api_key=abc123456",
            "api-key: abc123456",
        ] {
            let redacted = redact(assignment);
            assert!(
                redacted.contains("[REDACTED]"),
                "{assignment:?} produced {redacted:?}"
            );
            assert!(!redacted.contains("abcdef123"));
        }
    }

    #[test]
    fn redacts_pem_private_key_blocks() {
        let begin = ["-----", "BEGIN ", "PRIVATE KEY-----"].concat();
        let end = ["-----", "END ", "PRIVATE KEY-----"].concat();
        let body = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC";
        let pem = [begin.clone(), body.to_string(), end].join("\n");
        assert_eq!(redact(&pem), "[REDACTED]");
        let rsa_begin = ["-----", "BEGIN ", "RSA PRIVATE KEY-----"].concat();
        let rsa_end = ["-----", "END ", "RSA PRIVATE KEY-----"].concat();
        assert_eq!(
            redact(&[rsa_begin, body.to_string(), rsa_end].join("\n")),
            "[REDACTED]"
        );
        // An unterminated block is redacted to the end of the text.
        let truncated = [begin, body.to_string()].join("\n");
        assert_eq!(redact(&truncated), "[REDACTED]");
    }

    #[test]
    fn redacts_jwts() {
        let jwt = [
            format!("eyJ{}", "a".repeat(10)),
            "b".repeat(10),
            "c".repeat(10),
        ]
        .join(".");
        assert_eq!(redact(&jwt), "[REDACTED]");
    }

    #[test]
    fn redacts_url_credentials() {
        let url = format!("{}user:{}@example.com/path", "https://", "s3cretpass");
        assert_eq!(
            redact(&url),
            format!("{}[REDACTED]@example.com/path", "https://")
        );
    }

    #[test]
    fn redacts_email_addresses() {
        assert_eq!(redact("mail alice@example.com."), "mail [REDACTED].");
        assert_eq!(redact("a.b+c@sub.example.co"), "[REDACTED]");
    }

    #[test]
    fn redacts_home_paths() {
        for root in [home_users(), home_root()] {
            let path = format!("{root}/alice/secret");
            let redacted = redact(&path);
            assert_eq!(redacted, "[REDACTED]/secret");
            assert!(!redacted.contains("alice"));
        }
    }

    #[test]
    fn keeps_prose_and_embedded_prefixes_intact() {
        for prose in [
            "Keep the token budget under 5,000.",
            "Enforce a 5,000-token budget for root memory.",
            "Never commit secret files to git.",
            "Use argon2 for password hashing.",
            "See #high-risk-decision-protocol for details.",
        ] {
            assert_eq!(redact(prose), prose);
        }
        // A prefix glued to a longer identifier is not a boundary match.
        let glued = format!("x{}", fake(&["sk-"], 'a', 24));
        assert_eq!(redact(&glued), glued);
    }

    #[test]
    fn redacts_every_secret_in_a_dense_line() {
        let first = fake(&["sk-"], 'a', 24);
        let second = fake(&["gh", "p_"], 'b', 24);
        let redacted = redact(&format!("{first},{second}"));
        assert_eq!(redacted, "[REDACTED],[REDACTED]");
    }

    #[test]
    fn has_hygiene_hit_flags_each_pattern_family() {
        let hits = [
            fake(&["sk-"], 'a', 24),
            fake(&["gh", "p_"], 'b', 24),
            fake(&["git", "hub", "_pat_"], 'c', 24),
            fake(&["shp", "at_"], 'd', 24),
            fake(&["xox", "b-"], 'e', 12),
            format!("{}{}", "AKIA", "ABCDEFGHIJKLMNOP"),
            fake(&["AIza"], 'f', 35),
            "api_key=abcdef123".to_string(),
            "Authorization: Bearer abcdefgh".to_string(),
            [
                format!("eyJ{}", "a".repeat(10)),
                "b".repeat(10),
                "c".repeat(10),
            ]
            .join("."),
            format!("{}/alice/repo", home_users()),
            ["-----", "BEGIN ", "PRIVATE KEY-----"].concat(),
            format!("{}user:pass@host", "https://"),
        ];
        for line in hits {
            assert!(has_hygiene_hit(&line), "{line:?} was not a hygiene hit");
        }
        for line in [
            "Keep the token budget under 5,000.",
            "Use argon2 for password hashing.",
            "mail alice@example.com",
        ] {
            assert!(!has_hygiene_hit(line), "{line:?} was a false hit");
        }
    }

    #[test]
    fn fold_collapses_whitespace() {
        assert_eq!(fold("  a \n\t b  c "), "a b c");
        assert_eq!(fold(""), "");
        assert_eq!(fold("one"), "one");
    }

    #[test]
    fn clip_folds_and_truncates_on_char_boundaries() {
        assert_eq!(clip("short", 10), "short");
        assert_eq!(clip("  many   spaces\nhere ", 50), "many spaces here");
        let long = "x".repeat(20);
        let clipped = clip(&long, 10);
        assert_eq!(clipped.chars().count(), 10);
        assert!(clipped.ends_with('…'));
        let unicode = clip("日本語テキスト", 4);
        assert_eq!(unicode, "日本語…");
        assert_eq!(unicode.chars().count(), 4);
    }
}
