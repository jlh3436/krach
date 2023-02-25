#!/usr/bin/env python3
# General-purpose KRACH ratings calculator, based on:
#   Bradley-Terry Model: https://en.wikipedia.org/wiki/Bradley%E2%80%93Terry_model
#   http://elynah.com/tbrw/tbrw.cgi?krach
# See readme.md for more details.

import sys
import logging
import datetime
import dataclasses

#----------------------------------------------------------------------------
@dataclasses.dataclass
class Options:
    # Options to determine when to stop recursing through the KRACH algorithm.
    maxIterations:     int   = 1000       # max number of loops
    maxRatingsDiff:    float = 0.00001    # max diff between two runs that is considered "equal"

    # Options that control how shootout wins/losses and ties are weighted in the rankings
    shootoutWinValue:  float = 1.00       # loss value is (1.0 - winValue)
    tieValue:          float = 0.50

    # Number of fake ties to add to every teams record; Used to 'regularize' teams with
    # undefeated records.
    fakeTies:          int   = 1

    # Explicit list of teams to remove from the final rankings
    filteredTeams:     list  = dataclasses.field(default_factory=lambda: [])

    # Remove any teams from the final rankings that have not played this many games.
    # Value of 0 includes all teams.
    minGamesPlayed:    int   = 0

    # Determine how final ratings are scaled for display. 0 is auto-scale (i.e. multiply
    # all ratings by 10 until all ratings are > 1.0).
    scaleFactor:       int   = 0

    def dict(self):
        return {
            "Max Iterations"      : "{}".format(self.maxIterations),
            "Max Ratings Diff"    : "{}".format(self.maxRatingsDiff),
            "Shootout Win Value"  : "{:3.2f}".format(self.shootoutWinValue),
            "Shootout Loss Value" : "{:3.2f}".format(1.0 - self.shootoutWinValue),
            "Tie Value"           : "{:3.2f}".format(self.tieValue),
            "Fake Ties"           : "{}".format(self.fakeTies),
            "Ignore teams"        : "{}".format(",".join(self.filteredTeams)),
            "Min Games Played"    : "{}".format(self.minGamesPlayed),
        }

    def __str__(self):
        return '\n'.join([""] + [ "  {:<20} : {}".format(k, v) for k,v in self.dict().items() ])

#----------------------------------------------------------------------------
def removeTeam(ratings, team):
    if team in ratings:
        ratings.pop(team)

#----------------------------------------------------------------------------
def filterTeams(options, ledger, ratings):
    # use intermediate mapping to allow ignoring case in filtered teams
    icaseTeams = { name.lower() : name for name in ratings.keys() }
    # remove teams explicitly called out
    for team in options.filteredTeams:
        camelTeam = icaseTeams.get(team.lower(), None)
        if camelTeam:
            removeTeam(ratings, camelTeam)

    for name,team in ledger.teams.items():
        if team.record.played < options.minGamesPlayed:
            removeTeam(ratings, name)

#----------------------------------------------------------------------------
def scaleRankings(scaleFactor, ratings, sosAll):
    def _scale(x):
        return int(scaleFactor * x + 0.5)

    if scaleFactor == 0:
        # brute force search for a scaling factor that will
        # allow all ratings to be displayed as integers
        scaleFactor = 1
        for rating in ratings.values():
            while rating and _scale(rating) <= 0:
                scaleFactor *= 10

        # Also scale such that the max value has at least 4 digits
        while len(str(_scale(max(ratings.values())))) < 4:
            scaleFactor *= 10

        logging.debug("Auto-scaling all ratings by {}".format(scaleFactor))
    else:
        logging.debug("Hard scaling all ratings by {}".format(scaleFactor))

    for team in ratings:
        ratings[team] = _scale(ratings[team])

    for team in sosAll:
        sosAll[team] = _scale(sosAll[team])

#----------------------------------------------------------------------------
@dataclasses.dataclass
class Record:
    played:   int = 0
    wins:     int = 0
    losses:   int = 0
    soWins:   int = 0
    soLosses: int = 0
    ties:     int = 0

    def __str__(self):
        return f"{self.wins:>2}-{self.losses:>2}-{self.soWins:>2}-{self.soLosses:>2}-{self.ties:>2}"

    def addWin(self):
        self.played += 1
        self.wins += 1

    def addLoss(self):
        self.played += 1
        self.losses += 1

    def addShootoutWin(self):
        self.played += 1
        self.soWins += 1

    def addShootoutLoss(self):
        self.played += 1
        self.soLosses += 1

    def addTie(self):
        self.played += 1
        self.ties += 1

    def winPoints(self, options):
        return self.wins \
            + (self.soWins   * options.shootoutWinValue) \
            + (self.soLosses * (1.0 - options.shootoutWinValue)) \
            + (self.ties     * options.tieValue)

    def lossPoints(self, options):
        return self.played - self.winPoints(options)

#----------------------------------------------------------------------------
class Team:
    def __init__(self):
        self.matchups = dict()
        self.record = Record()

    def addOpponent(self, opponent):
        if opponent not in self.matchups:
            self.matchups[opponent] = Record()

    def addWin(self, opponent):
        self.record.addWin()
        self.addOpponent(opponent)
        self.matchups[opponent].addWin()

    def addLoss(self, opponent):
        self.record.addLoss()
        self.addOpponent(opponent)
        self.matchups[opponent].addLoss()

    def addShootoutWin(self, opponent):
        self.record.addShootoutWin()
        self.addOpponent(opponent)
        self.matchups[opponent].addShootoutWin()

    def addShootoutLoss(self, opponent):
        self.record.addShootoutLoss()
        self.addOpponent(opponent)
        self.matchups[opponent].addShootoutLoss()

    def addTie(self, opponent):
        self.record.addTie()
        self.addOpponent(opponent)
        self.matchups[opponent].addTie()

#----------------------------------------------------------------------------
# Tracks all teams and their game results.
class Ledger:
    def __init__(self, dateCutoff):
        self.dateCutoff = dateCutoff
        self.teams = dict()
        self.oldestGame = None
        self.newestGame = None

    def isValid(self, date):
        return date <= self.dateCutoff

    def addGame(self, date, winner, loser):
        self.addTeam(winner)
        self.addTeam(loser)
        if self.isValid(date):
            self.recordDate(date)
            self.teams[winner].addWin(loser)
            self.teams[loser ].addLoss(winner)

    def addShootout(self, date, winner, loser):
        self.addTeam(winner)
        self.addTeam(loser)
        if self.isValid(date):
            self.recordDate(date)
            self.teams[winner].addShootoutWin(loser)
            self.teams[loser ].addShootoutLoss(winner)

    def addTie(self, date, team1, team2):
        self.addTeam(team1)
        self.addTeam(team2)
        if self.isValid(date):
            self.recordDate(date)
            self.teams[team1].addTie(team2)
            self.teams[team2].addTie(team1)

    def addTeam(self, team):
        if not team in self.teams:
            self.teams[team] = Team()

    def recordDate(self, date):
        if not self.oldestGame or date < self.oldestGame:
            self.oldestGame = date
        if not self.newestGame or date > self.newestGame:
            self.newestGame = date

#----------------------------------------------------------------------------
@dataclasses.dataclass
class Rating:
    name:      str = ""     # Name of the team, used for display and lookup in ledger
    value:     int   = 100  # KRACH rating value
    sos:       float = 100  # strength-of-schedule
    expected:  float = 0.0  # Predicted number of wins based on KRACH ratings
    diff:      float = 0.0  # Difference between expected and actual number of wins (absolute)
    odds:      dict  = dataclasses.field(default_factory=lambda: dict())

#----------------------------------------------------------------------------
# Implements the KRACH algorithm.
class KRACH:
    def __init__(self, options):
        self.options = options

    #----------------------------------------------------------------------------
    # Execute the KRACH algorithm until the ratings converge, or
    # we hit our max iteration limit.
    def run(self, ledger) -> dict[str, float]:
        # Initial guesses at the krach ratings; doesn't really matter as we'll iterate
        # until we get to the correct values.
        ratings = { k : 1.0 for k in ledger.teams.keys() }

        loop = 0
        while (self.options.maxIterations <= 0) or (self.options.maxIterations > 0 and loop < self.options.maxIterations):
            loop += 1
            updated = self.calculateAll(ledger, ratings)
            if self.areRatingsEqual(ratings, updated):
                logging.debug("Convergence to final results took {} interations".format(loop))
                return updated
            ratings = updated

        logging.debug("Failed to reach convergence after {} interations".format(loop))
        return ratings

    #----------------------------------------------------------------------------
    # Calculate new KRACH ratings for all teams
    def calculateAll(self, ledger, ratings):
        updated = dict()
        for name in ledger.teams:
            updated[name] = self.calculate(ledger, ratings, name)
        return self.normalize(updated)

    #----------------------------------------------------------------------------
    # Calculates an updated rating for a single team, using:
    #   Ki = Vi / ( ∑j Nij / (Ki + Kj) )
    def calculate(self, ledger, ratings, i):
        return ledger.teams[i].record.winPoints(self.options) / self.calculateMatchupFactor(ledger, ratings, i)

    #----------------------------------------------------------------------------
    # Calculate: ∑j Nij / (Ki + Kj)
    def calculateMatchupFactor(self, ledger, ratings, i):
        myTeam = ledger.teams[i]
        sumOfMatchups = 0.0
        # iterate across all teams we've played
        for j in myTeam.matchups:
            gp = myTeam.matchups[j].played
            sumOfMatchups += (gp) / (ratings[i] + ratings[j])
        return sumOfMatchups

    #----------------------------------------------------------------------------
    def strengthOfScheduleAll(self, ledger, ratings):
        return { team : self.strengthOfSchedule(ledger, ratings, team) for team in ledger.teams }

    #----------------------------------------------------------------------------
    def strengthOfSchedule(self, ledger, ratings, myTeam):
        total = 0.0
        for oppTeam in ledger.teams[myTeam].matchups:
            total += ledger.teams[myTeam].matchups[oppTeam].played * ratings[oppTeam]
        return total / ledger.teams[myTeam].record.played

    #----------------------------------------------------------------------------
    def normalize(self, ratings):
        total = sum(ratings.values())
        return { name : value / total for name,value in ratings.items() }

    #----------------------------------------------------------------------------
    def areRatingsEqual(self, original, updated):
        return sum(abs(original[team] - updated[team]) for team in original) < self.options.maxRatingsDiff

    #----------------------------------------------------------------------------
    def expectedWinsAll(self, ledger, ratings):
        return { team : self.expectedWins(ledger, ratings, team) for team in ledger.teams }

    #----------------------------------------------------------------------------
    # Validate KRACH ratings by calculating the expected wins using:
    #    Vi = ∑j Nij*Ki/(Ki+Kj)
    def expectedWins(self, ledger, ratings, myTeam):
        return ratings[myTeam] * self.calculateMatchupFactor(ledger, ratings, myTeam)

    #----------------------------------------------------------------------------
    def calculateOdds(self, ratings):
        return { team : self.calculateTeamOdds(team, ratings) for team in ratings }

    #----------------------------------------------------------------------------
    def calculateTeamOdds(self, team, ratings):
        def _calcOdds(rating1, rating2):
            try:
                return (rating1 / (rating1 + rating2))
            except:
                return float("NaN")

        myRating = ratings[team]
        return { oppTeam : _calcOdds(myRating, oppRating) for oppTeam,oppRating in ratings.items() }

#----------------------------------------------------------------------------
def addFakeTies(options, ledger):
    fakeTeam = "__KRACH_FAKE_TEAM__"

    for _ in range(options.fakeTies):
        if not fakeTeam in options.filteredTeams:
            options.filteredTeams.append(fakeTeam)

        ledger.addTeam(fakeTeam)
        for realTeam in ledger.teams:
            if realTeam != fakeTeam:
                ledger.addTie(ledger.oldestGame, fakeTeam, realTeam)

#----------------------------------------------------------------------------
def generate(options, ledger):
    # Add in any fake game data
    addFakeTies(options, ledger)

    krach = KRACH(options)
    ratings = krach.run(ledger)

    # Calculate final strength of schedules
    sosAll = krach.strengthOfScheduleAll(ledger, ratings)

    # Validate ratings by converting back to expected number of wins
    expectedWins = krach.expectedWinsAll(ledger, ratings)

    # Now that we're done all calculations, remove any ignored teams
    # (such as showcase teams)
    filterTeams(options, ledger, ratings)

    odds = krach.calculateOdds(ratings)

    # scale up so all values are integers
    scaleRankings(options.scaleFactor, ratings, sosAll)

    # sort by self ratings, highest first.
    ratings = sorted(ratings.items(), key=lambda kv: kv[1], reverse = True)

    # And finally, build a list of Rating() objects for easy consumption by caller
    def _rating(name, value):
        # difference between number of expected wins and actual wins
        # negative differerence indicates the KRACH rating is too low, likewise a
        # positive difference indicates rating is too high.
        diff = expectedWins[name] - ledger.teams[name].record.winPoints(options)
        return Rating(name, value, sosAll[name], expectedWins[name], diff, odds[name])

    return [ _rating(name,value) for name,value in ratings ]

