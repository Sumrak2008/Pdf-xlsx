# Сборка PdfXlsx из исходного кода

Это руководство — для разработчиков, которые хотят собрать портативную
Windows-сборку самостоятельно или запустить программу из исходного кода для
разработки.

## Сборка готового портативного архива (Windows)

Используется единый сценарий `tools/build_windows.ps1` — тот же самый,
который запускает GitHub Actions при публикации релиза
(`.github/workflows/release.yml`), поэтому локальная сборка и сборка в CI
не могут незаметно разойтись.

### Требования

- Windows 10/11, 64-разрядная версия.
- Python 3.11 или 3.12, добавленный в PATH.
- [Chocolatey](https://chocolatey.org/install), добавленный в PATH (нужен
  только для установки движка Tesseract OCR на этапе сборки; в готовой
  программе Chocolatey не участвует и не упоминается).
- Доступ к Интернету **только на время сборки** (для `pip install` и
  скачивания Tesseract/языковых данных). Готовая программа в сеть не
  обращается никогда — см. [SECURITY_OFFLINE.md](SECURITY_OFFLINE.md).

### Запуск

```powershell
pwsh -File tools/build_windows.ps1
```

Сценарий выполняет по порядку:

1. Считывает номер версии из `src/pdfxlsx/version.py`.
2. Устанавливает зависимости из `requirements-dev.txt`.
3. Запускает PyInstaller (`pyinstaller --noconfirm pdfxlsx.spec`) — создаётся
   папка `dist/PdfXlsx/` (`--onedir`: один `.exe` и папка `_internal` с
   зависимостями; никаких архивов или установщиков).
4. Устанавливает Tesseract OCR через Chocolatey (если ещё не установлен) и
   копирует сам движок и его DLL-файлы в `dist/PdfXlsx/tools/tesseract/`.
5. Скачивает три файла языковых данных — `eng.traineddata`,
   `rus.traineddata`, `osd.traineddata` — из официального репозитория
   `tesseract-ocr/tessdata_fast` в `dist/PdfXlsx/tools/tesseract/tessdata/`.
6. Архивирует `dist/PdfXlsx/` в
   `artifacts/PdfXlsx-<версия>-windows-x64.zip` и считает его SHA-256,
   сохраняя контрольную сумму в файл `<имя_архива>.sha256` рядом.

Результат — самодостаточная папка `dist/PdfXlsx/`, которую можно скопировать
на любой компьютер с Windows 10/11 x64 и запустить без установки.

## Автоматическая сборка и релиз (GitHub Actions)

При отправке тега вида `v*.*.*` (например, `v1.0.0`) workflow
`.github/workflows/release.yml` автоматически:

1. Запускает `tools/build_windows.ps1` на раннере `windows-latest`.
2. Загружает получившийся ZIP-архив и файл с контрольной суммой как артефакт
   сборки.
3. Создаёт GitHub Release с этими файлами и автоматически сформированными
   примечаниями к выпуску.

Workflow `.github/workflows/ci.yml` запускается при каждом push и каждом
pull request: проверяет код линтером `ruff`, запускает тесты `pytest`, а
также собирает программу через PyInstaller и проверяет, что собранный
исполняемый файл запускается и не падает сразу же (`pytest -m smoke`).

## Запуск из исходного кода (для разработки)

Платформонезависимо (Linux/macOS/Windows), без сборки PyInstaller:

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pdfxlsx
```

В режиме разработки (не из собранного `.exe`) программа сама ищет системную
установку Tesseract OCR (см. `src/pdfxlsx/core/paths.py`), так что
встроенный `tools/tesseract/` не обязателен — достаточно установленного в
системе `tesseract` с языковыми пакетами `rus`/`eng`. Это сделано только
для удобства разработки: в собранной программе (`is_frozen() == True`)
никакого обращения к системному Tesseract нет, используется исключительно
встроенная копия.

### Тесты и линтер

```bash
ruff check src/ tests/ tools/
QT_QPA_PLATFORM=offscreen pytest -v
```

GUI-тесты используют `QT_QPA_PLATFORM=offscreen`, чтобы работать без
графического дисплея (например, в CI). «Дымовой» тест сборки
(`pytest -m smoke`) не входит в обычный запуск `pytest` — он запускает
полную сборку PyInstaller и поэтому медленный; запускайте его отдельно,
когда нужно проверить именно упаковку.
