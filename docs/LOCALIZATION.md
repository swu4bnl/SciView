# UI message catalog

SciView's owned interface text lives in the YAML catalogs under
[`src/sciview/interfaces/locales/en-US`](../src/sciview/interfaces/locales/en-US).
The locale folder uses the BCP 47 tag `en-US`; each catalog is organized by
interface or workflow. These are the English source catalogs;
translated text is currently maintained separately in Qt TS/QM files.

## Entries

Each entry has a stable semantic ID, English `text`, and a concise `context`
field describing the control's purpose. Context is translator metadata, not
visible help text. Describe the affected object, action, and scientific
distinctions when relevant; do not explain hypothetical mistranslations.

```yaml
viewer.pan.label:
  text: Pan
  context: Image-viewer tool for moving the displayed image by dragging with the mouse.

image_browser.images_found:
  text: "Found {count} images"
  context: Status after scanning the selected folder.
  placeholders:
    count: Number of image files found.
```

Use separate IDs for separate meanings, even if English wording matches.
Keep related captions, tooltips, and accessible names in the same domain.
Preserve complete messages rather than translating and joining fragments.
Named placeholders and their format specifications must survive translation.
Literal braces in a formatted message must be doubled.

Call `tr("domain.message", count=count)` from the presentation layer.
Missing IDs, invalid catalogs, and mismatched placeholders raise explicit
errors. English is the source language; without an installed translation,
Qt returns the English source text.

## Translation workflow

Export all source entries and their guidance for Qt Linguist:

```console
python -m sciview.interfaces.export_translations sciview_fr.ts --language fr_FR
```

The exporter refuses to overwrite an existing file. It writes the stable ID as Qt's disambiguation comment and context
plus placeholder descriptions as translator notes. Translate the TS file in
Qt Linguist and compile it to QM with Qt's `lrelease` tool. Install a
`QTranslator` on the application **before constructing widgets**. Keep the
translator alive for the lifetime of the application. The YAML catalogs hold
the English source text and translator context; Qt TS/QM files hold translated
text and should use Qt locale codes such as `fr_FR`.

The lookup API currently loads source messages from `en-US` and uses Qt
context `SciView`, the English source, and the stable
ID as disambiguation. Existing widgets do not automatically retranslate when
the translator changes; live language switching and a language selector are
not implemented. The exporter produces a fresh source catalog; use Qt's
`lconvert`/`lupdate` workflow to merge source updates into maintained
translations rather than overwriting completed work.

For developer-only validation, set `SCIVIEW_DEV_LOCALE` before launching the
application. For example, in PowerShell:

```powershell
$env:SCIVIEW_DEV_LOCALE = "zh-CN"
pixi run launch-app
Remove-Item Env:SCIVIEW_DEV_LOCALE
```

Unset the variable to launch with the English source catalogs. This override
is intended for development checks, is not a user setting, and does not add a
language selector to the application. The selected locale catalog must match
the English catalog IDs, translator context, and placeholder definitions.
SciView bundles Source Sans 3 (3.052) and Noto Sans CJK SC (regular and bold) for consistent
sans-serif rendering across platforms. Startup registers these files with Qt
and Matplotlib before creating views; Chinese preview does not require
host-installed CJK fonts. Source Sans 3 is the primary family, with Noto Sans CJK SC
providing Chinese glyphs. The Style Inspector can still override the UI family.

Both fonts use the SIL Open Font License 1.1. Their copyright/license notices
ship alongside the font files under `src/sciview/interfaces/fonts/`.
Redistribution does not require SciView or exported figures to adopt that
license. Unmodified upstream font files are used:

- [Source Sans 3 release](https://github.com/adobe-fonts/source-sans/releases/tag/3.052R).
- [Noto Sans CJK SC source](https://github.com/notofonts/noto-cjk/tree/f8d157532fbfaeda587e826d4cd5b21a49186f7c/Sans/OTF/SimplifiedChinese).

The four font files add approximately 33 MiB before wheel compression. Keep
their license notices when updating or redistributing the package.

This migration preserves existing English number/count wording. It does not
introduce language-specific plural forms or locale-aware number/date
formatting; those require explicit design before shipping a target language.

## Boundaries

- Translate labels, notes, tips, dialog text, status templates, and owned
  presentation errors.
- Keep machine keys, recipe fields, protocol identifiers, file extensions,
  scientific symbols/units, user data, paths, and external metadata unchanged.
  Store stable item data separately from translated selection labels.
- Keep raw external exception details and backend diagnostics intact. Wrap
  them in translated interface messages where appropriate; do not add Qt
  translation dependencies to scientific backends.
- Developer console logs, setup/diagnostic CLI tools, and archived interfaces
  are not part of the runtime catalog. Developer UI text is cataloged separately.

Catalog YAML is package data. Tests validate the catalog contract, formatting,
Qt translation routing, and export metadata rather than freezing incidental
English wording or widget geometry.
