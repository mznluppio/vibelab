"""Regression coverage for DNS-safe preview hostnames."""

from app.utils.resource_naming import (
    MAX_DNS_LABEL_LENGTH,
    get_container_hostname,
    get_dns_safe_label,
)


def test_short_container_hostname_is_unchanged() -> None:
    assert (
        get_container_hostname("my-project-abc123", "frontend", "localhost")
        == "my-project-abc123-frontend.localhost"
    )


def test_long_container_hostname_has_dns_safe_label_and_readable_prefix() -> None:
    hostname = get_container_hostname(
        "organiser-les-reservations-de-salles-de-reunion-dq89ej",
        "nextjs-16-base",
        "localhost",
    )
    label, domain = hostname.split(".", 1)

    assert domain == "localhost"
    assert len(label) <= MAX_DNS_LABEL_LENGTH
    assert label.startswith("organiser-les-reservations-de-salles-de-reunion")
    assert label.endswith("-" + get_dns_safe_label(
        "organiser-les-reservations-de-salles-de-reunion-dq89ej-nextjs-16-base"
    ).rsplit("-", 1)[1])


def test_long_container_hostnames_do_not_collide_when_prefixes_match() -> None:
    prefix = "a" * 70
    first = get_container_hostname(prefix + "-first", "web", "localhost")
    second = get_container_hostname(prefix + "-second", "web", "localhost")

    assert first != second
    assert len(first.split(".", 1)[0]) <= MAX_DNS_LABEL_LENGTH
    assert len(second.split(".", 1)[0]) <= MAX_DNS_LABEL_LENGTH
