# Publishing PT Alarm to the Home Assistant Marketplace

Since Home Assistant 2026.11, HACS is built into Home Assistant as the **Marketplace** (Settings → Marketplace). It uses the same catalog ([hacs/default](https://github.com/hacs/default)), the same `hacs.json` and the same validation action. Publisher docs: <https://contributors.home-assistant.io/marketplace/>

## Requirements checklist

| Requirement | Status |
|---|---|
| One integration per repo in `custom_components/pt_alarm/` | ✅ |
| `hacs.json` at the root with `name` | ✅ |
| `manifest.json` with `version`, `issue_tracker`, `documentation`, `codeowners` | ✅ (replace the username placeholders) |
| `categories` in the manifest (known value, 1–3) | ✅ `security_safety.alarm_systems` |
| Domain not used by a core integration | ✅ `pt_alarm` |
| Finished translations in `translations/en.json` (no `strings.json`) | ✅ |
| Brand images in `custom_components/pt_alarm/brand/` (`icon.png` required) | ✅ icon, dark_icon, logo, dark_logo + @2x |
| README with images | ✅ |
| hassfest + HACS action workflow, passing without `ignore` | ✅ `.github/workflows/validate.yaml` |
| Repo has a description, topics and issues enabled | ⬜ set on GitHub |
| A full GitHub **release** (a tag alone is not enough) | ⬜ step 3 |

## 1. Set your GitHub username

✅ Done. The repository is `https://github.com/powertbs/pt-alarm`, and the manifest, README and card all point to it.

## 2. Push to GitHub (GitHub Desktop)

1. **File → Add local repository** and choose this folder. It is already a git repository.
2. Commit all files to `main`. Use the summary `Initial release of PT Alarm`.
3. **Publish repository**, name it `pt-alarm`, and **uncheck "Keep this code private"**. The Marketplace only works with public repos.
4. On github.com, open the repo and go to **⚙ (About)**:
   - Description: `Alarm system for Home Assistant with a dashboard card`
   - Topics: `home-assistant`, `hacs`, `marketplace`, `integration`, `alarm`
5. Under **Settings → General → Features**, make sure **Issues** is checked.
6. Under **Actions**, check that **Validate** (HACS + hassfest) is green.

## 3. Create a release

1. Go to **Releases → Draft a new release**, create the tag `v1.0.0` and set the title `v1.0.0`, then **Publish release**.
2. The **Release** workflow attaches `pt_alarm.zip` automatically. The Marketplace installs from that file (`zip_release` in `hacs.json`).

People can now install it through **Settings → Marketplace → Add from link**.

## 4. Get into the default catalog (optional, recommended)

You must submit this from your **personal** GitHub account, not an organization. Reviews can take months.

1. Fork [hacs/default](https://github.com/hacs/default) and create a new branch from `master`.
2. Add `<your-username>/pt-alarm` to the `integration` file, in alphabetical order.
3. Open a PR and fill in the template completely. It needs links to:
   - your latest release
   - a passing HACS action run (without `ignore`)
   - a passing hassfest run
4. Don't request reviewers. PRs that request reviews are closed.

## Releasing updates

1. Bump `VERSION` in `const.py`, `version` in `manifest.json` and `CARD_VERSION` in `frontend/pt-alarm-card.js`.
2. If a release needs a newer Home Assistant version, raise `homeassistant` in `hacs.json`.
3. Publish a new GitHub release (`v1.0.1`, and so on). The Marketplace offers it as an update.

Users report Marketplace bugs to Home Assistant, but PT Alarm bugs come to **your** GitHub issues, so keep an eye on them.
