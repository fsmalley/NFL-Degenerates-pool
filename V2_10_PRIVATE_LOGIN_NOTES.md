# V2.10 — Private Member Login

## Member experience
Visitors are redirected to `/login` before any pool content can be opened. The landing page is titled **NFL Degenerates** and uses a football field/stadium background.

After the correct shared member password is entered, the member can use Draft, Survivor, Confidence, results, standings, and the other authenticated pages normally.

## Commissioner password management
Commissioner/Test Lab contains a **Change Member Site Password** card. Enter:
1. Commissioner password
2. New member password
3. Confirm new member password

The new member password is hashed before being stored in Supabase.

## Initial / recovery access
If no stored member password exists yet, `SITE_PASSWORD` is used when configured. Otherwise the existing `ADMIN_PASSWORD` is accepted as the initial site password. Once a separate member password is stored, members must use that new password.

## Database
Run `v2_10_private_login_schema_update.sql` once before deployment.
