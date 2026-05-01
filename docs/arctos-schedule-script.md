# Arctos Schedule Script Documentation

## Introduction

Arctos Schedule Script, or *ASS*, is a lisp-style language meant for
expressing skip conditions.

It was designed with three goals in mind:

- express any arbitrary skip condition
- keep the grammar as simple as possible
- don't give people remote code execution

Enter as the skip condition an expression that reduces to a boolean
(`true` or `false`). The moment all of a match's dependencies are
completed, this expression will be evaluated. If it evaluates to
`true`, the match will be skipped! If it evaluates to *anything else*
nothing will happen (asterisk; see [When are things
evaluated?](#when-are-things-evaluated)).

## Syntax Introduction

An ASS expression is either an *atom* (a literal value or a function)
or a *list* (of expressions). 

Some examples of atoms are:

- numbers: `1`, `2`, etc.
- booleans: `true`, `false`
- nil: `nil` (the "nothing value")
- functions: `+`, `and`, `if`, etc.

A list is a space-separated list of items. The parser tries to reduce
expressions into atoms. It deals with lists by calling the first
element of the list with the remainder of the list as arguments. if
the first argument is not a list, it can't do anything, so it just
gives up and lets the expression be a list.

Take the following list for example:

```
(+ 1 2)
```

the first element is `+`, which is a function that takes two
arguments. The parser knows how to call `+` and so this list can be
reduced to the atom `3`.

```
(- (* 2 3) (+ 2 3))
```

This simplifies to `(- 6 5)` which is of course `1`.

## Team and Match Literals

Teams and matches are both types of atoms. A team literal can be
written with square brackets. The options for what you put inside the
square brackets are the same as the options for setting teams/ref
teams for a match; all of the following are valid:

```
[ursae]
[MatchNameHere::winner]
[MatchNameHere::loser]
[tag::TagNameHere]
```

Matches can be written similarly: simply enclose the match name in
curly braces like `{MatchNameHere}`.

the following functions can be used to get info about a team:

- `(wins [TeamName])` - Number of wins for a team this event
- `(losses [TeamName])` - Number of losses for a team this event
- `(points-won [TeamName])` - Total points won by a team this event
- `(points-lost [TeamName])` - Total points lost by a team this event
- `(points-won [TeamName] {MatchName})` - Points won in a specific match
- `(points-lost [TeamName] {MatchName})` - Points lost in a specific match

And the following functions can get info about matches:

- `(winner {MatchName})` - Winning team of a match (fails to evaluate
  until match is done)
- `(loser {MatchName})` - Losing team of a match (fails to evaluate
  until match is done)
- `(is-skipped {MatchName})` - Whether a match will be skipped (fails
  to evaluate until the match has either been skipped or started)

The `::winner` and `::loser` options for teams are largely there for
consistency; it is recommended to instead use `(winner
{MatchNameHere})` and `(loser {MatchNameHere})`.

## Lists

You can construct a list using the `cons` function.

```
(cons 1 2 3) -> the bare list 1 2 3
(1 2 3) -> cannot call 1 as a function
```

this works because you can think of the parenthesis surrounding a
written list as if they were instructions to the parser to call the
first item in the list. The list returned by `cons` doesn't have
parenthesis around it, so it's fine (but you can't write these as a
literal).

Now here are some fun things you can do with lists:

- `(car LIST)`  - get first element of the list
- `(cdr LIST)` - get all but the first element of the list
- `(get INDEX LIST)` get the value of the list at index `INDEX` (so
  `(car LIST)` is equivalent to `(get 0 LIST)`)
- `(len LIST)` - get the length of the list

## Maps, Reductions and Lambdas

Now, lists are only really useful if you can loop through them, but we
haven't introduced any form of looping yet. Since this is a functional
language, we don't have the familiar concepts like for loops and while
loops, but we do have `map`, `reduce`, and `lambda`.

First, `lambda` creates a function. The following expression is a
function that takes two arguments, `a`, `b`, and `c`, and returns
`a*b + c`.

```
(lambda (a b c) (+ c (* a b)))
```

Now, we can use `map` and `reduce` to apply functions to lists. 
`map` just applies a function to every element of the list. 

```
(map (cons -2 -1 0 1 2) (lambda (x) (* (- x 1) (- x 1))))
```
The above expression reduces to the list `9 4 1 0 1`.


`reduce` is a little more complicated: it takes a function with two arguments and uses it to combine all the arguments of the list. For example, to sum all elements, we can do this:

```
(reduce (cons 1 2 5 3 4) (lambda (a b) (+ a b)))
```

and we get the correct answer of `15`. Or we can take the max of the list by using the maximum function:

```
(reduce (cons 1 2 5 3 4) (lambda (a b) (if (> a b) a b)))
```

Some of these can be tedious to impelment, so i've included some builtins:

- `(max LIST)` - get the max value
- `(min LIST)` - get the min value
- `(max_by LIST FUNC)` - get the max value of a list using `FUNC` as a key
- `(min_by LIST FUNC)` - get the min value of a list using `FUNC` as a key


## When are things evaluated?

Everything is evaluated when a match's last dependency becomes
finished or skipped. If it is not skipped, the skip condition will be
re-evaluated every time a match starts or finishes until it is started
or the skip condition evaluates to `true` and it gets skipped.

## Cheat Sheet

### Basic Values

- `true` - True  
- `false` - False  
- `nil` - Nil  
- `[TeamName]` - Team name (username, `tag::TagName`, or `MatchName::winner` / `MatchName::loser`)  
- `{MatchName}` - Match name  

### Basic Operations

- `(== A B)` - Equality comparison  
- `(> A B)`, `(< A B)`, `(>= A B)`, `(<= A B)` - Numeric comparisons  
- `(and A B)`, `(or A B)`, `(not A)` - Logical operations  

### Team Operations

- `(wins [TeamName])` - Number of wins for a team  
- `(losses [TeamName])` - Number of losses for a team  
- `(points-won [TeamName])` - Total points won by a team  
- `(points-lost [TeamName])` - Total points lost by a team  
- `(points-won [TeamName] {MatchName})` - Points won in a specific match  
- `(points-lost [TeamName] {MatchName})` - Points lost in a specific match  
- `(is-skipped {MatchName})` - True if match status is SKIPPED, false if IN_PROGRESS or COMPLETED  

### Match Operations

- `(winner {MatchName})` - Winner team of a match (returns team or NIL)  
- `(loser {MatchName})` - Loser team of a match (returns team or NIL)  

### Other Operations

- `(if CONDITION IF_TRUE IF_FALSE)` - If condition is true, return IF_TRUE, otherwise return IF_FALSE  
- `(lambda (*args) (output))` - Define a lambda function  
- `(cons *_ )` - Create a list from the arguments  
- `(car LIST)` - Get the first element of a list  
- `(cdr LIST)` - Get the rest of a list  
- `(get INDEX LIST)` - Get the element at index  
- `(or-default VAL DEFAULT)` - Returns VAL if VAL is not NIL else DEFAULT  
- `(len LIST)` - Length of a list  
- `(map LIST FUNC)` - Apply a function to each element of a list  
- `(reduce LIST FUNC)` - Reduce a list to a single value  
- `(max LIST)`, `(min LIST)` - Max/min value in a list  
- `(max_by LIST FUNC)`, `(min_by LIST FUNC)` - Max/min by a function  

### Examples

- `(== 0 (losses [TeamName]))` - Skip if team has no losses  
- `(> (wins [TeamA]) (wins [TeamB]))` - Skip if TeamA has more wins than TeamB  
- `(== (winner {Match1}) [TeamName])` - Skip if TeamName won Match1  


