# Brandweerrooster API v1.3.8

## Facebook message classification

- Added a new `{classificatie}` Facebook template placeholder.
- The default Facebook message now includes a readable incident classification in the heading, for example `Buitenbrand` or `Woningbrand`.
- Common Dutch P2000/Brandweerrooster fire classifications are normalized automatically.
- Unknown classifications are preserved in a cleaned-up form instead of being guessed.
- Existing user-created `facebook_template.yaml` files are not overwritten. The previous built-in default is migrated automatically so existing default installations also receive the new classification line.
- The assigned-personnel fix from v1.3.7 is retained.
- The diagnostic sensor from v1.3.6/1.3.7 remains in this test build for verification and should be removed before the final public release.
