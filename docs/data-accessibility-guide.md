# Data Accessibility Guide

Updated: Dec 28, 2025

This document details when and how data that you explicitly enter is accessible to others.

## Never published, in any way:

Arctos will never publish any of this information to anyone:
 - email address
 - phone number, if entered
 - password/oauth secret info

## Injuries

 - if public, all data published
 - if private:
     - if not healed, shown to refs when they start a match
     - Description, date, and status may be shown, but will be anonymized (not tied to you in any way)

## Ref Notes (on players or teams):
 - visible forever on target's profile to all explicitly listed head refs and TOs for the tournament at which they were logged
 - visible during tournament on target's profile to all head refs for the tournament at which they were logged
 - visible to head refs when starting or viewing a match in the same tournament in which they were logged
 - visible to target forever on their profile
 - may be shown in aggregate statistics, but timestamp will be rounded to the day, the author will not be shown, and the target will not be shown (other than the type  - team or player)

!!! important "Future Changes"
    the promises about ref note privacy may change in the future, but a) users will be notified of any such changes, and b) they will not apply retrospectively (ie, these rules will always apply to notes written under these rules)

## Encryption/sysadmin disclaimer

All of this being said, none of the data dealt with by Arctos is actually encrypted - anyone with server access could view private information (though authentication data is actually secure). The server itself is very secure, but you do have to trust the sysadmins to not leak information (to be clear, they will not).