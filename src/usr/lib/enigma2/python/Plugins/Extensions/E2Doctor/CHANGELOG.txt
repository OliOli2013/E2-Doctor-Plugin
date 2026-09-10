# E2 Doctor 2.4.1 — 2026-09-10

- Przywrócona szata graficzna z wersji 2.3: logo, ocena kondycji, kolorowe liczniki i lista modułów.
- Przywrócona paleta i układ ekranów pomocniczych oraz aktualizatora.
- Zachowane poprawki diagnostyki, aktualizacji, bezpieczeństwa plików i narzędzi z 2.4.0.
- Poprzedni panel współpracuje ze skanowaniem i zapisywaniem raportów w tle.
- Zachowanie wybranego modułu po odświeżeniu; oczekiwanie na skan przed raportem lub naprawą.
- Korekta odstępów w wierszach listy; większy obszar starego aktualizatora HD, aby status nie nachodził na przyciski.
- 22 testy lokalne. Fizyczny tuner nadal wymaga weryfikacji.

# E2 Doctor 2.4.0 — 2026-09-10

- Nowy panel AIO: trzy kolumny, nieprzezroczyste tło i turkusowe akcenty.
- Skanowanie, analiza IPK/Python i pobieranie aktualizacji w tle; komunikaty postępu.
- Poprawki diagnostyki TLS, OPKG, lamedb5 i analizy crashlogów.
- Prywatne pliki tymczasowe; limity czasu/rozmiaru; SHA-256 oraz kontrola nazwy, wersji i architektury paczki.
- Sprawdzenie faktycznie zainstalowanych plików po zakończeniu OPKG.
- Ostrożniejsze czyszczenie starych crashlogów, kopie i przywracanie bukietów.
- Wyłączenie podejrzanej wtyczki poza drzewem skanowanym przez Enigma2.
- Maskowanie rozpoznanych sekretów w raportach i nowy raport awaryjny bez GUI.
- Usunięcie 43 przesłoniętych definicji; wydzielenie modułów; powtarzalne pakowanie i 20 testów.

Pełna lista ustaleń i granic testów: `docs/AUDYT-2.4.0-PL.md`.
