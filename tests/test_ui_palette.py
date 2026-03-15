from src.utils import get_status_badge, get_update_badge, get_changed_count_badge

def test_get_status_badge_enhanced():
    # Verify enhanced behavior
    badge = get_status_badge("RECRUITING")
    assert 'class="badge bg-success"' in badge
    assert 'aria-label="Status: Recruiting"' in badge
    assert 'title="Original status: RECRUITING"' in badge
    assert '🟢 Recruiting' in badge

def test_get_status_badge_unknown():
    # Verify fallback for unknown status
    badge = get_status_badge("UNKNOWN_STATE")
    assert 'class="badge bg-light text-dark"' in badge
    assert 'aria-label="Status: Unknown State"' in badge
    assert '⚪ Unknown State' in badge

def test_get_update_badge():
    badge = get_update_badge("Changed")
    assert 'aria-label="Changes detected"' in badge
    assert 'title="Changes detected since last crawl"' in badge
    assert '🔴 Changed' in badge

    badge = get_update_badge("No Change")
    assert 'aria-label="No recent changes"' in badge
    assert 'title="No changes detected since last crawl"' in badge
    assert '🟢 No Change' in badge

def test_get_changed_count_badge():
    badge = get_changed_count_badge(5)
    assert 'aria-label="5 trials changed"' in badge
    assert 'title="5 trials have updates"' in badge
    assert '🔴 5' in badge

    badge = get_changed_count_badge(0)
    assert 'aria-label="No trials changed"' in badge
    assert 'title="No trials have updates"' in badge
    assert '🟢 0' in badge
