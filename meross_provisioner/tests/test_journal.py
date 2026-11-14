from __future__ import annotations

import json

from meross_provisioner.journal import TransactionJournal


def test_journal_round_trips_recovery_metadata_without_secrets(tmp_path) -> None:
    journal = TransactionJournal(tmp_path / "transaction.json")
    state = {
        "interface": "wlan0",
        "access_point_addon_slug": "local_test_ap",
        "phase": "temporary_profile_created",
        "ap_was_running": True,
        "remove_temporary_profile": True,
    }

    journal.write(state)

    assert journal.read() == state
    assert not (tmp_path / "transaction.json").read_bytes().startswith(b"\xef\xbb\xbf")


def test_journal_returns_none_for_corrupt_state(tmp_path) -> None:
    path = tmp_path / "transaction.json"
    path.write_text("not-json", encoding="utf-8")

    assert TransactionJournal(path).read() is None


def test_journal_clear_is_idempotent(tmp_path) -> None:
    journal = TransactionJournal(tmp_path / "transaction.json")
    journal.write(
        {
            "interface": "wlan0",
            "access_point_addon_slug": "ap",
            "phase": "stopping_ap",
            "ap_was_running": True,
            "remove_temporary_profile": False,
        }
    )

    journal.clear()
    journal.clear()

    assert journal.read() is None


def test_journal_serializes_only_explicitly_supplied_state(tmp_path) -> None:
    journal = TransactionJournal(tmp_path / "transaction.json")
    journal.write(
        {
            "interface": "wlan0",
            "phase": "stopping_ap",
            "ap_was_running": True,
            "access_point_addon_slug": "ap",
            "remove_temporary_profile": False,
        }
    )

    saved = json.loads((tmp_path / "transaction.json").read_text(encoding="utf-8"))
    assert "password" not in saved
    assert "target_ssid" not in saved


def test_journal_rejects_secret_fields(tmp_path) -> None:
    journal = TransactionJournal(tmp_path / "transaction.json")
    state = {
        "interface": "wlan0",
        "access_point_addon_slug": "ap",
        "phase": "stopping_ap",
        "ap_was_running": True,
        "remove_temporary_profile": False,
        "password": "must-not-be-written",
    }

    try:
        journal.write(state)
    except ValueError as err:
        assert "unsupported fields" in str(err)
    else:
        raise AssertionError("A secret-bearing journal entry was accepted.")
    assert not (tmp_path / "transaction.json").exists()
