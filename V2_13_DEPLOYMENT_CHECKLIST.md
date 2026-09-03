# V2.13 — One-Time Deployment Checklist

This version was designed so the member-account rollout can be deployed in one application upload.

## Before the application upload

1. Keep the working V2.12.2 deployment available as your rollback baseline.
2. Open the Supabase project used by NFL Degenerates.
3. Open **SQL Editor**.
4. Run the complete file:
   `v2_13_member_accounts_schema_update.sql`
5. Confirm the SQL completes without an error.

Do not create member accounts directly in Supabase. Use the website Commissioner controls after V2.13 is deployed.

## Application upload

6. Upload/deploy the V2.13 application package to GitHub/Render using the same process used for previous versions.
7. Wait for Render to complete deployment.
8. Open `/health`. The response should report status `ok` and include `member_accounts` in the checks.

## First Commissioner setup

9. Enter the existing shared NFL Degenerates site password.
10. On the new personal member sign-in screen, choose **Open Commissioner Test Lab**.
11. In **Manage Individual Members**, enter the existing Commissioner password and click **Load / Refresh Members**.
12. Create your personal account first. The first account is automatically assigned the **COMMISSIONER** role.
13. Sign out of the personal-account layer and sign back in using that new Commissioner username and temporary password.
14. Create your private password when prompted.

## Create the remaining members

15. Return to **Commissioner → Manage Individual Members**.
16. For Draft Pool players, use **Create Missing Draft Accounts** if desired. Copy or print the temporary credential list immediately.
17. Add any non-Draft members individually.
18. Review each person's Draft, Survivor, and Confidence identity assignments.
19. Give each member only their own username and temporary password.

## Recommended verification before announcing accounts

20. Test one normal MEMBER account:
    - shared site password works
    - individual sign-in works
    - first-login password change is required
    - dashboard shows the correct name
    - Survivor automatically uses the correct player
    - Confidence automatically uses the correct test player
    - Pool Talk shows the verified member name
    - Commissioner controls are hidden

21. Test the COMMISSIONER account:
    - Commissioner navigation appears
    - Test Lab opens
    - member management loads
    - password reset works
    - Draft/Survivor/forum Commissioner controls remain available

22. Run **Commissioner → Run Quality Checks**.

## Rollback

If an application issue is found, redeploy the known-good V2.12.2 application. The V2.13 Supabase table and nullable forum columns may remain in place; V2.12.2 does not depend on them and will ignore them.
