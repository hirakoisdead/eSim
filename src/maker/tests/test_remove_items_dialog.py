"""Tests for the searchable multi-select RemoveItemsDialog that replaced the
old unscrollable QComboBox model/lint_off pickers in the NgVeri tab."""
from maker.RemoveItemsDialog import RemoveItemsDialog


# ── matches(): pure, no QApplication needed ────────────────────────────────

def test_matches_is_case_insensitive_substring():
    assert RemoveItemsDialog.matches("CounterTop", "top")
    assert RemoveItemsDialog.matches("adder8", "DD")


def test_matches_empty_query_matches_everything():
    assert RemoveItemsDialog.matches("anything", "")
    assert RemoveItemsDialog.matches("anything", "   ")


def test_matches_rejects_non_substring():
    assert not RemoveItemsDialog.matches("mux", "adder")


# ── dialog behaviour (needs a QApplication) ────────────────────────────────

def test_items_listed_sorted_case_insensitively(qapp):
    dlg = RemoveItemsDialog("t", ["beta", "Alpha", "gamma"])
    shown = [dlg.listw.item(i).text() for i in range(dlg.listw.count())]
    assert shown == ["Alpha", "beta", "gamma"]


def test_filter_hides_non_matching_rows(qapp):
    dlg = RemoveItemsDialog("t", ["adder", "mux", "counter"])
    dlg.search.setText("co")
    visible = [dlg.listw.item(i).text()
               for i in range(dlg.listw.count())
               if not dlg.listw.isRowHidden(i)]
    assert visible == ["counter"]


def test_selected_items_returns_every_chosen_name(qapp):
    dlg = RemoveItemsDialog("t", ["a", "b", "c"])
    dlg.listw.item(0).setSelected(True)
    dlg.listw.item(2).setSelected(True)
    assert sorted(dlg.selected_items()) == ["a", "c"]


def test_remove_button_enabled_only_with_a_selection(qapp):
    dlg = RemoveItemsDialog("t", ["a", "b"])
    assert not dlg.remove_btn.isEnabled()
    dlg.listw.item(0).setSelected(True)
    assert dlg.remove_btn.isEnabled()


def test_empty_list_shows_placeholder_and_no_selectable_rows(qapp):
    dlg = RemoveItemsDialog("t", [], item_noun="model")
    assert dlg.listw.count() == 1
    placeholder = dlg.listw.item(0)
    assert "no models to remove" in placeholder.text()
    assert dlg.selected_items() == []
