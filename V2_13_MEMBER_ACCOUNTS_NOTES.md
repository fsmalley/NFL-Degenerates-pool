# V2.13 — Individual Member Accounts

V2.13 builds on the confirmed V2.12.2 baseline.

## Member access flow

1. Member enters the existing shared private-site password.
2. Member signs in to an individual account with username and password.
3. A temporary password forces a password change on first login.
4. The member lands on a personalized dashboard.
5. Survivor, Confidence testing, and Pool Talk automatically use the authenticated member identity.

The shared site password remains in place as the first privacy gate.

## Member account fields

Each account has:
- permanent internal numeric ID
- username plus normalized case-insensitive username key
- display name
- secure Werkzeug password hash
- role: MEMBER or COMMISSIONER
- active/inactive state
- first-login password-change flag
- optional Draft player ID
- Survivor player key
- Confidence player key
- creation/update timestamps
- last-login timestamp

Plaintext member passwords are never stored.

## Commissioner controls

Commissioner Test Lab now includes **Manage Individual Members**.

The Commissioner can:
- create a member account
- choose MEMBER or COMMISSIONER role
- connect a Draft player record
- connect Survivor and Confidence identities
- activate/deactivate accounts
- reset a member to a temporary password
- see the member's last login
- bulk-create missing accounts from the Draft player list

The first account is automatically forced to COMMISSIONER to prevent setup lockout. The server also prevents demoting or deactivating the only active Commissioner account.

### Bulk Create from Draft Players

After the first Commissioner account exists, **Create Missing Draft Accounts** creates an account for every Draft player not already linked.

For each newly-created account it:
- uses the Draft player name as display name and username where possible
- assigns the Draft player ID
- prepares matching Survivor and Confidence identity keys
- generates a unique temporary password
- requires the member to change the password on first login

The temporary credential list is shown immediately after creation. It should be copied or printed then because the plaintext passwords are not stored and cannot be displayed again.

## Personalized dashboard

The Member Dashboard now greets the signed-in member and adds a **My Pools** section.

It shows:
- Draft rank, running total, and linked roster status
- current Survivor submission / elimination status
- current Confidence test-entry status
- reminder that official Confidence picks remain on Football Frenzy

## Survivor

Logged-in members no longer type a name or Survivor PIN. The authenticated account supplies the player identity.

Existing Survivor data and legacy PIN hashes remain in the database for compatibility.

## Confidence Pool

Logged-in members no longer type a player name or Confidence PIN.

The Confidence Pool remains explicitly marked as **testing only**. Official Confidence Pool picks must continue to be submitted through Football Frenzy until testing is complete.

Existing Confidence PIN hashes remain for backward compatibility.

## Pool Talk

New forum topics and replies use the authenticated member display name. Members can no longer type an arbitrary forum author name.

V2.13 also stores `member_account_id` on new forum topics/replies, while old V2.11 forum content remains valid.

## Commissioner visibility

Normal MEMBER accounts no longer see normal Commissioner navigation or editing/moderation controls. Sensitive server-side Commissioner operations continue to require the existing `ADMIN_PASSWORD`.

## Database update

Run:

`v2_13_member_accounts_schema_update.sql`

This creates `member_accounts` and adds nullable member-account links to the existing forum tables.

The migration intentionally does not delete or rewrite any existing Draft, Survivor, Confidence, site setting, or forum data.
