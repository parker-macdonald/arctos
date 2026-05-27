pub const URL_SLUG_ALLOWED_HINT: &str = "URL slugs may only contain letters, numbers, or -_~.";

pub fn is_valid_url_slug(value: &str) -> bool {
    !value.is_empty()
        && value
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '~' | '.'))
}
