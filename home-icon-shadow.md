---
name: CSA auth design
description: Key decisions and quirks in the Computer Skills Academy auth flow
---

# CSA Auth Design

## showOnboarding default
`showOnboarding` starts `true` so the login screen renders immediately on mount.
The device-auth `useEffect` sets it `false` only when the stored JSON passes validation
(`isLoggedIn===true`, `studentId` matches, valid StudentId).
Before this fix, it started `false` and only became `true` after `hydrated` fired — causing a blank screen window.

## "kkj" master password
Intentional per owner spec. In `LoginScreen.handleLogin`, `password === "kkj"` calls `onComplete(selected)` directly, skipping `firebaseLogin`. No Firebase Auth session is created for this path — Firestore sync won't work during admin "kkj" sessions. This is accepted: admin only reads localStorage data.

**Why:** Owner wants a single master credential to access any student profile for monitoring.

## adminSession must always be reset on logout
Both `handleLogout` and `handleFactoryReset` must call `setAdminSession({ isActive: false, ... })`.
Omitting this causes admin mode to carry over to the login screen / next student — privilege leak.

## Change password
`changePassword(studentId, newPin)` in `lib/auth.ts` calls `updateStudentPassword` (Firebase `updatePassword`) then saves locally. Requires a recent Firebase session — if session is old, Firebase returns `auth/requires-recent-login`; the UI shows "log out and back in first".

## Firebase env vars
All 8 `NEXT_PUBLIC_FIREBASE_*` vars set as Replit shared env vars (not secrets — these are public client-side config values). API keys (NVIDIA, MIMO, YouTube) remain in `.env` which is gitignored.
