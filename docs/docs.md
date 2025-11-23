# User Documentation

Complete guide to using the tournament management system

## Table of Contents

- [Ref Notes Visibility](#ref-notes-visibility)
- [Scheduling and Ribbon Games](#scheduling-and-ribbon-games)
- [YouTube Livestream Integration](#youtube-livestream-integration)
- [Running Games (for Tournament Organizers)](#running-games-for-tournament-organizers)
- [Running Games (for Head Refs)](#running-games-for-head-refs)

---

## Ref Notes Visibility

Ref notes (also called match notes) are a way for head refs to record important information about teams, players, and matches. Understanding who can see these notes is important for maintaining appropriate privacy and transparency.

### Who Can See Ref Notes?

- **Team Notes:** Team notes (notes with target "team1" or "team2") are visible to:
  - The team themselves (when viewing their own team profile)
  - Head refs in any tournament (when viewing any team profile)

- **Player Notes:** Player notes are visible to:
  - The player themselves (when viewing their own player profile)
  - Head refs in any tournament (when viewing any player profile)

- **Match Notes:** General match notes (not tied to a specific team or player) are visible to:
  - Head refs who are authorized to ref that specific match

- **Point Notes:** Notes attached to specific points are visible to:
  - Head refs who are authorized to ref that match

> **Note:** Regular players and teams cannot see notes about other teams or players - only their own. This ensures that sensitive information recorded by refs remains appropriately private while still being accessible to those who need it.

**[SCREENSHOT NEEDED]**

**Location:** Team profile page showing notes section

**What to show:** A team profile page with ref notes visible, demonstrating that the team can see notes about themselves. Annotate to show:
- Where notes appear on the team profile
- How notes are formatted (with timestamps, point references if applicable)
- That notes are clearly labeled as coming from matches

---

## Scheduling and Ribbon Games

All matches have (among other things) the following information:
- nominal start time
- nominal length
- previous match (if one exists)
- next match (if one exists)

### Static Scheduling

In the *static scheduling* paradigm (implemented by the `static` match type), all match start times must be set concretely before the event starts. This means that teams can be penalized for tardiness because the schedule is very clear about what time they need to show up (ie, it's not just 'show up promptly after the previous match ends'). If head refs then cut off matches after the nominal length, the tournament can guarantee the safety of the schedule.

Unless you are willing to cut a large portion of matches short, however, this requires a large nominal length, which leads to lots of idle time before every match starts (see: Fog of War 2025). To fix this, we introduce the *dynamic scheduling*, implemented by the `dynamic` match type.

### Dynamic Matches

Dynamic matches do not have a nominal start time (that you, the TO, can set, at least). Instead, their nominal start time is computed based on the nominal length of their dependencies. Match dependencies are:
- the preceding match: this match has to wait until the previous match is over.
- dependent teams: if "match1 winner" is one of the teams playing or reffing in this match, this match is dependent on match 1

The system sets this match's start time to the latest possible end time across all dependencies.

The magic happens when matches begin to be completed. Every time a match is completed, we update all other matches. If a match ends early, its end time will be earlier than its nominal length would predict, and so subsequent matches will be shifted forward! This seems great, but it creates a problem: it breaks our ability to tell teams when they need to be at their matches. If we shift their matches forward, we can't possibly penalize them for being late.

To solve this, we lock the start time of dynamic matches when the last of their dependency matches starts. When this happens, matches are marked as "time finalized" on the schedule. This means that teams always know their matches' start times at least nominal_length ahead of time, so it's reasonable to expect them to be on time.

> **Note:** Matches without dependencies (like the first match of the day) must be static.

### Breaks

Break matches represent dynamically scheduled breaks in the tournament. They just reserve time (ie, for a lunch break) on a field in a way that can be pulled forward if matches finish early.

If you want a non-dynamic break, just use static matches before and after the break, and leave the break empty.

### Join

Join matches are like thread joins in multithreading: they are dynamically-scheduled zero-length entries in the schedule that follow the rule that all joins with the same name must occur at the same time. More practically, for example, you could put a join match on each field (all sharing the same name) after all morning matches on that field, and then a lunch break on each field, then afternoon matches afterwards. This would ensure that all teams have at least the length of the break overlapping in their lunches (unless they choose to start afternoon games early).

### Ribbon Games

Ribbon games are matches that are not counted in tournament results. They are useful for exhibition matches, practice games, or matches that don't affect standings. When creating or editing a match, you can check the "Ribbon Game" checkbox to mark it as such.

Ribbon games will still appear on the schedule and can be run normally, but they won't affect tournament standings, statistics, or bracket progression.

**[SCREENSHOT NEEDED]**

**Location:** Tournament setup page, match creation/edit form

**What to show:** The match creation form with the "Ribbon Game" checkbox visible. Annotate to show:
- Where the Ribbon Game checkbox is located
- The match type dropdown (showing static, dynamic, break, join options)
- How to set match dependencies

---

## YouTube Livestream Integration

The system can automatically link points in a match to their starting timestamps in a YouTube livestream, making it easy to review footage directly from match pages.

### Setting Up Livestream Integration

1. Go to your tournament's setup page and configure fields
2. For each field that will be livestreamed, you need to add the YouTube stream URL to the field's "stream" attribute
3. To get the embed link:
   1. Go to your YouTube stream
   2. Click **Share** → **Embed**
   3. Copy the link inside the `src="..."` attribute of the embed code
4. Paste this link into the field's stream configuration

### How It Works

Once configured, the system will:
- Automatically detect when a livestream starts using the YouTube Data API
- Track the stream start time relative to when points are scored
- Display clickable timestamps on match pages that jump directly to the relevant moment in the stream
- Allow head refs to manually adjust timestamps if needed

> **Note:** This feature requires a YouTube Data API key to be configured on the server. If no API key is available, the system will still work but won't be able to automatically detect stream start times.

**[SCREENSHOT NEEDED]**

**Location:** Field configuration in tournament setup, and match page showing stream integration

**What to show:**
- Screenshot 1: Field setup page showing where to enter the YouTube stream URL
- Screenshot 2: Match page showing the YouTube player embedded and point timestamps that link to the stream
- Annotate to show how clicking a timestamp jumps to that moment in the video

---

## Running Games (for Tournament Organizers)

As a Tournament Organizer, you have oversight of all matches, but typically head refs will be running individual matches. However, there are several tools and features you should understand.

### Stones Feature

For matches using the STONES set type, there is a special "stones" audio player that provides synchronized audio cues. The stones countdown is synced across:
- The match page (where head refs run the match)
- The public match view page
- The OBS scoreboard overlay
- The dedicated stones player page (accessible at `/stones`)

All of these views stay synchronized using server time and a Kalman filter to account for network latency. This ensures that everyone sees the same stones countdown, whether they're watching on a phone, tablet, or computer.

The stones player page allows you to play audio files that correspond to the stones countdown. Different audio files can be selected, and the system will automatically play the appropriate sound when stones reach certain thresholds (typically when stones reach 0).

**[SCREENSHOT NEEDED]**

**Location:** Stones player page and match page showing stones countdown

**What to show:**
- The stones player page showing available audio files and the countdown
- The match page showing the stones remaining counter
- Annotate to show that both are displaying the same countdown value

### Head Ref Authorization

As a TO, you control who can head ref matches in your tournament. This is configured in the tournament settings page under "Head Ref Options". There are several ways to authorize head refs:

- **Explicit List:** You can provide a comma-separated list of player usernames who are always allowed to head ref, regardless of their registration status.
- **Allow Anyone:** When enabled, any player who is registered for the tournament (with status "CONFIRMED") can head ref matches.
- **Reffing Teams:** When enabled, players who are registered on teams assigned to ref a specific match can head ref that match. This is useful when you assign reffing duties to specific teams.

**Important:** Only player accounts can head ref matches, not team accounts. This is to enforce accountability for ref responsibilities, as team accounts can be shared.

Head refs can only start and run matches they are authorized for. The system checks authorization when:
- A head ref tries to start a match
- A head ref tries to access the match running page
- A head ref tries to add notes or modify match data

**[SCREENSHOT NEEDED]**

**Location:** Tournament settings page, Head Ref Options section

**What to show:** The Head Ref Options section with all three authorization methods visible. Annotate to show:
- Where to enter the explicit list of allowed usernames
- The "Allow anyone" checkbox
- The "Only allow reffing teams" checkbox
- The explanatory text about player accounts vs team accounts

### OBS Scoreboard Integration

The system provides a public scoreboard endpoint that can be embedded in OBS (Open Broadcaster Software) or other streaming software as a browser source. This creates a live scoreboard overlay for your stream.

#### Setting Up the Scoreboard in OBS

1. In OBS, add a new **Browser Source**
2. Set the URL to: `/api/scoreboard?tournament=TOURNAMENT_URL&field=FIELD_NAME`
   - Replace `TOURNAMENT_URL` with your tournament's URL
   - Replace `FIELD_NAME` with the name of the field you're streaming
3. Set the width and height (recommended: 1920x1080 or match your stream resolution)
4. Check "Shutdown source when not visible" if you want it to stop updating when not shown
5. The scoreboard will automatically update to show the currently active match on that field

The scoreboard displays:
- Team names and logos/photos
- Current score by set
- For STONES matches: the stones remaining countdown with a progress bar
- When no match is active: information about the previous and next matches on that field

The scoreboard automatically polls for updates and refreshes when match state changes. For STONES matches, the countdown updates in real-time using the same synchronization system as the match pages.

**[SCREENSHOT NEEDED]**

**Location:** OBS browser source configuration and the scoreboard page itself

**What to show:**
- Screenshot 1: OBS browser source settings showing the URL configuration
- Screenshot 2: The scoreboard page displaying an active match with team names, scores, and stones countdown
- Annotate to show the URL format and how the scoreboard looks in OBS

---

## Running Games (for Head Refs)

As a head ref, you are responsible for running individual matches. This section covers everything you need to know about managing matches from start to finish.

### All Data is Good Data: Don't Delete Points!

**Important Philosophy:** The system is designed around the principle that "all data is good data." This means you should never delete points, even if they were rerolled or need to be corrected.

Instead of deleting points:
- **Mark points as rerolled:** If a point needs to be rerolled, use the "Rerolled" checkbox on the point. Rerolled points are excluded from scoring but remain in the match history.
- **Update point winners:** If you recorded the wrong winner, simply change the winner dropdown - the point stays in the record.
- **Adjust set numbers:** If a point was recorded in the wrong set, use the set number controls to move it to the correct set.

This approach ensures a complete audit trail of everything that happened during the match, which is valuable for reviewing disputes, understanding match flow, and maintaining accurate statistics.

**[SCREENSHOT NEEDED]**

**Location:** Match running page, points table

**What to show:** The points table showing:
- A point with the "Rerolled" checkbox checked
- How rerolled points are visually distinguished (if they are)
- The set number controls (+ and - buttons)
- Annotate to emphasize that there is no delete button for points, only the reroll checkbox

### Arbitrary Set Assignment

You can assign any point to any set number, regardless of when it was scored. This is useful for:
- **Correcting mistakes:** If you accidentally recorded a point in the wrong set, you can move it later.
- **Handling set boundaries:** Sometimes it's unclear when a set ended. You can adjust set assignments after the fact to match the actual set structure.
- **Special formats:** For matches with unusual set structures, you have full control over how points are grouped into sets.

To change a point's set number, use the **+** and **−** buttons next to the set number in the points table. The set number cannot go below 1.

The score-by-set display automatically updates to reflect your set assignments, and rerolled points are excluded from scoring calculations.

**[SCREENSHOT NEEDED]**

**Location:** Match running page, points table with set number controls

**What to show:**
- The set number controls (+ and - buttons) clearly visible
- Multiple points with different set numbers to show flexibility
- The score-by-set table showing how points are grouped
- Annotate to show how changing a set number updates the score display

### Adding Notes

You can add notes at several levels to record important information:
- **Match Notes:** General notes about the match (visible to head refs for this match)
- **Team Notes:** Notes about a specific team (visible to that team and all head refs)
- **Player Notes:** Notes about a specific player (visible to that player and all head refs)
- **Point Notes:** Notes attached to a specific point (visible to head refs for this match)

To add notes:
1. On the match running page, find the notes section or the "Notes" button for a specific point
2. Enter your note text
3. Optionally select a target (team1, team2, match, or a specific player)
4. If adding a point note, select the point first
5. Submit the note

Notes are timestamped and include who created them. They're useful for:
- Recording injuries or substitutions
- Noting rule interpretations or disputes
- Tracking patterns or concerns about teams/players
- Documenting special circumstances

**[SCREENSHOT NEEDED]**

**Location:** Match running page, notes interface

**What to show:**
- The notes input form showing text field and target dropdown
- How to add a note to a specific point (the Notes button in the points table)
- A list of existing notes showing timestamps and creators
- Annotate to show the different note types and where they appear

### Starting Matches

Before starting a match, you'll see the match start page where you can:
- **View existing notes and injuries:** The system shows you any relevant notes about the teams and players, as well as any active injuries for players. This information is displayed when you select players for each team.
- **Add mercenaries (mercs):** You can search for and add players who aren't on either team's roster. This is useful for pickup games or when teams need additional players. Use the search box to find players by name, jersey name, or jersey number.
- **Select players for each team:** Check boxes to select which players will play for each team. Players are shown with their jersey information if available.

#### Constraints When Starting Matches

The system enforces several constraints to prevent errors:
- **Maximum field size:** You cannot select more players than the tournament's maximum field size (configured by the TO). If you try to select too many players, you'll get an error message.
- **Unpaid players:** Players who haven't paid their registration fee cannot be selected. They will appear grayed out with an "Unpaid" badge. You must ensure players have paid before they can participate.
- **No duplicate players:** A player cannot be on both teams simultaneously. If you try to select a player for both teams, the system will prevent it.
- **Player already on other team:** If a player is selected for one team, they cannot be selected for the other team until you uncheck them from the first team.

#### When to Actually Start the Match

You should start the match when:
- Both teams are ready to play
- All players are selected and confirmed
- You've reviewed any relevant notes or injuries
- You're ready to begin scoring points

**Important:** Once you start a match, you cannot un-start it. The match status changes to "IN_PROGRESS" and the confirmed start time is recorded. Make sure everything is correct before clicking "Start Match".

If a team doesn't show up, you can still start the match with zero players for that team - the system will prompt you to confirm this unusual situation.

For STONES matches, you'll also need to set the "stones per set" value before starting. This determines how many stones each set will have.

**[SCREENSHOT NEEDED]**

**Location:** Match start page

**What to show:**
- The player selection interface showing checkboxes for each team
- An unpaid player shown grayed out with "Unpaid" badge
- A player with an active injury displayed
- The "View Notes" button and notes modal
- The search box for adding mercs
- The match notes textarea
- For STONES matches: the stones per set input field
- Annotate to show all the constraints and features mentioned above

### Running the Match

Once the match is started, you'll be taken to the match running page where you can:
- Add points as they're scored
- Update point winners, set numbers, and reroll status
- Add notes about the match, teams, players, or specific points
- For STONES matches: monitor and update the stones countdown
- Finalize the match when it's complete

The match page updates in real-time, and changes are synchronized across all viewers (head refs, public viewers, and scoreboard overlays).

**[SCREENSHOT NEEDED]**

**Location:** Match running page (full view)

**What to show:**
- The complete match running interface
- Score by set display
- Points table with all controls visible
- Add point button
- Notes section
- For STONES matches: stones countdown display
- Finalize match button
- Annotate to show the workflow of running a match

