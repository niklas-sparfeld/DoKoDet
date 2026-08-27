# DokoDetector glossary

This glossary defines the canonical domain language for DokoDetector. These meanings are
immutable. Use them in plans, documentation, code, schemas, APIs, fixtures, and user interfaces.

## Gameplay terms

### Player

A person who takes part in a game.

### Game

A set of rounds. A game typically has `player count × 4` rounds. Calculate the final score over all
rounds in the game.

A game is typically played during one evening. The players can continue the game on another day.

### Round

A set of 10 tricks. Each trick has four played cards. One player is the dealer for the round.

### Trick

One of the 10 units in a round. A trick contains one card play from each of the four active
players.

### Dealer

The player who deals the cards for a round. The dealer can sit out that round.

### Active player

A player who takes part in a specific round. Each round has four active players.

### Card play

The act of an active player playing one card into the current trick.

### Player hand

The cards held by one active player during a round and not yet played. Use **human hand** for the
body part when the distinction matters in vision work.

### Turn

One active player's required opportunity to make a card play in a trick.

### Trick leader

The active player who makes the first card play in a trick.

### Trick winner

The active player who wins a trick under the round rules.

### Round score

The score contribution produced by one round.

### Game score

The score calculated over all round scores in a game. The final game score is not the score of one
round.

## Activity and recording terms

### Session

One occasion during which related game or staged activity occurs in a shared physical setting.

A session can contain all or parts of multiple games. A game can span multiple sessions. A session
can also contain staged activity without a game. Starting or stopping a recording does not start or
end a session.

For example, one session can contain the final rounds of one game and the first 10 rounds of the
next game. A set of staged kitchen recordings can form another session without a game.

### Recording

Media captured during one uninterrupted start-to-stop capture. A recording belongs to one session.
It can contain parts of multiple games or staged activity.

### Staged activity

Deliberately arranged actions that are not part of a game. Staged activity can imitate card plays,
tricks, or other situations. It does not contain canonical games or rounds.

### Table setup

A repeatable physical and visual arrangement, such as the table, deck, background, and camera
placement. A session can use more than one table setup.

### Operator

A person who controls recording, review, or data tooling. An operator can also be a player, but the
roles are not interchangeable.

## Evidence and data terms

### Source asset

Immutable imported bytes, such as an original video or accepted evidence package. A source asset
records or represents source material. It is not the real-world recording or activity itself.

### Event

A time-bounded occurrence that is relevant to detection or gameplay. Use a qualified event term
when its review state matters.

### Event proposal

A possible event reported by a person or model before review. An event proposal is not ground
truth.

### Reviewed event

An event that a person has confirmed through the review process.

### Evidence package

A bounded collection of recorded evidence around an event proposal. An evidence package can exist
without a reviewed event.

### Physical deck

One concrete set of physical cards used for a round or staged activity.

### Physical card

One concrete card in a physical deck. Two physical cards can have the same visual card identity.

### Deck design

The shared visible design of cards. Several physical decks can have the same deck design.

### Visual card identity

The visible suit-and-rank identity of a card, such as `HEARTS_QUEEN`. Two physical cards can have
the same visual card identity.

## Relationships

- A game contains rounds. A round belongs to one game.
- A game and a session have a many-to-many relationship.
- A recording belongs to one session. Recording boundaries do not define session boundaries.
- One recording can contain parts of multiple games or staged activity.
- Staged activity belongs to a session but not to a game or round.
- A source asset can contain data from a recording. It is not interchangeable with that recording.

## Terminology rules

- Use these terms only with the meanings above. This rule also applies to plurals, capitalization,
  identifiers, and compound terms.
- Do not use **game** for one round.
- Do not use **round** for one trick or for a complete game.
- Do not use **session** for one recording or for a dataset partition.
- Do not use **recording** for a session, source asset, or evidence package.
- Do not introduce a synonym for a canonical term.
- Qualify **event** as an **event proposal** or **reviewed event** when the review state matters.
- Add each new domain term to this glossary before its first use when it could overlap with a
  canonical term. Give the new term a distinct meaning.
- If existing text conflicts with this glossary, the glossary takes precedence. Update the
  conflicting text when that text is next changed.
