"""Russian word forms corroborate a topic without accepting shared prefixes."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent.recall_query import automatic_recall_terms, recall_has_topic


@pytest.mark.parametrize("text,term", [
    ("Файлы остаются в рабочем каталоге.", "файлами"),
    ("Елка находится рядом с домом.", "ёлками"),
    ("Регрессия воспроизведена.", "регрессиями"),
    ("Слайды готовы к просмотру.", "слайдами"),
])
def test_russian_inflections_corroborate_the_same_topic(text, term):
    assert recall_has_topic(text, [term])


@pytest.mark.parametrize("text,term", [
    ("Документирование программного интерфейса.", "документами"),
    ("Проекторы установлены в аудитории.", "проектирование"),
])
def test_shared_five_letter_prefix_is_not_morphological_evidence(text, term):
    assert not recall_has_topic(text, [term])


@pytest.mark.parametrize("identity", [
    "device-run-AX29", "/work/alpha/report.txt", "d7440d05-6643-4f04-adec-83b3f3409b12",
    "SN66M051EU/02",
])
def test_exact_object_constraints_are_not_stemmed(identity):
    assert recall_has_topic(identity, [identity.casefold()])
    assert not recall_has_topic(identity + "x", [identity.casefold()])


@pytest.mark.parametrize("query", ["Делай, разрешаю", "Да, продолжай", "Go ahead"])
def test_permission_only_request_remains_without_a_historical_topic(query):
    assert automatic_recall_terms(query, set()) == []
    assert not recall_has_topic("Исторические разрешения на работу с файлами.", [])


def test_parallel_corroboration_keeps_stemmer_state_isolated():
    pairs = [("Файлы сохранены.", ["файлами"]),
             ("Проекторы установлены.", ["проектирование"])] * 100
    with ThreadPoolExecutor(max_workers=8) as pool:
        actual = list(pool.map(lambda pair: recall_has_topic(*pair), pairs))
    assert actual == [True, False] * 100
