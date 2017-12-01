import os
import discord
import logging
import tabulate
from . import roll
from . import config
from . import backend

logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)
console = logging.StreamHandler()
console.setFormatter(logging.Formatter(config.LOG_FMT))
handler = logging.FileHandler(filename=config.LOG_PATH, encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter(config.LOG_FMT))
logger.addHandler(handler)
logger.addHandler(console)


class Sharkling(discord.Client):
    def __init__(self, fresh_run):
        super(Sharkling, self).__init__()
        self.__previous_roll = None
        self.__last_rolls = dict()
        self.__scores = dict() if fresh_run else backend.load(os.path.expandvars(config.SCORE_DATA_PATH))

    def run(self):
        @self.event
        async def on_ready():
            logger.info('{name} ({discord_id}) logged in!'.format(
                name=self.user.name, discord_id=self.user.id))

        @self.event
        async def on_message(message):

            if message.content.lower().startswith('!rol'):
                message.author.nick = message.author.nick if message.author.nick else str(message.author)
                message.timestamp = message.timestamp
                logger.info('[attempt] roll from "{owner}" at "{timestamp}"'.format(
                    owner=message.author.nick, timestamp=message.timestamp
                ))
                try:
                    # check if cooldown period has passed since last roll
                    if self.__last_rolls.get(message.author.nick) and \
                                    (message.timestamp - self.__last_rolls[
                                        message.author.nick].timestamp).total_seconds() < config.ROLL_COOLDOWN:
                        raise roll.OnCooldown(
                            message='take a breather and try again in a bit, {owner}'.format(owner=message.author.nick))

                    # check if this exact roll has been rolled before
                    attempted_roll = message.timestamp.strftime("%Y%m%d%H%M")
                    if self.__previous_roll and self.__previous_roll.timestamp.strftime("%Y%m%d%H%M")[
                                                roll.PRECEDENCE[0].LENGTH:] == attempted_roll[
                                                                               roll.PRECEDENCE[0].LENGTH:]:
                        raise roll.Duplicate(
                            '**{owner}** already rolled that one'.format(owner=self.__previous_roll.owner)
                        )
                    try:  # check if it is a roll to begin with, and not a failed attempt
                        latest_roll = roll.check(attempted_roll)(
                            owner=message.author.nick, timestamp=message.timestamp,
                            streak_multiplier=roll.get_streak_multiplier(message.author.nick, self.__previous_roll)
                        )
                    except (roll.BadRng, roll.GoodRng) as e:  # some rolls have random events
                        latest_roll, tag, reaction = e.roll, '{tag}'.format(tag=e.__class__.TAG), e.__class__.REACTION

                    else:
                        tag, reaction = 'CHECKED', '\U0001F64F'  # todo: move into config

                    try:  # increment the user's score
                        self.__scores[message.author.nick] += latest_roll.points
                    except KeyError:
                        self.__scores[message.author.nick] = latest_roll.points
                    finally:
                        self.__previous_roll = latest_roll
                        self.__last_rolls[message.author.nick] = latest_roll

                    # construct the successful roll reply message contents
                    reply = '**[{tag}]** {reply}. **{author}** now has {total} point{plural}.'.format(
                        reply=latest_roll, author=message.author.nick, total=self.__scores[message.author.nick],
                        plural='s' if self.__scores[message.author.nick] > 1 else '', tag=tag)

                    # decorate the user's roll message with an appropriate reaction depending on the outcome
                    await self.add_reaction(message, reaction)

                    logger.info('[success] {reply}'.format(reply=reply))

                except roll.Invalid as e:  # todo: group these together in the future
                    reply = '**[failure]** {error}'.format(error=e.message)
                    logger.info(reply)

                except roll.OnCooldown as e:
                    reply = '**[cooldown]** {error}'.format(error=e.message)
                    logger.info(reply)

                except roll.Duplicate as e:
                    reply = '**[duplicate]** {error}'.format(error=e.message)
                    logger.info(reply)

                await self.send_message(message.channel, reply)

                # save the user scores after every roll
                backend.save(self.__scores, os.path.expandvars(config.SCORE_DATA_PATH))

            elif message.content.startswith('!score'):
                # build a table of the scores and a short line with who is the author.nick of the last roll
                score = '```{table}\n\n{note}```'.format(table=tabulate.tabulate(
                    sorted(self.__scores.items(), key=lambda x: x[1], reverse=True), headers=['user', 'points']),
                    note='{streaker} is currently riding the {multiplier}x streak'.format(
                        streaker=self.__previous_roll.owner,
                        multiplier=self.__previous_roll.streak_multiplier
                    ) if self.__previous_roll else ''
                )
                await self.send_message(message.channel, score)

            elif message.content.startswith('!help'):
                help_message = '```{help_message}```'.format(help_message=tabulate.tabulate(
                    [
                        ('!roll', 'try your luck at a roll'),
                        ('!score', 'see the top rollers'),
                        ('!help', 'print this message')
                    ],
                    headers=['command', 'description']
                ))
                await self.send_message(message.channel, help_message)

        super(Sharkling, self).run(os.environ[config.DISCORD_TOKEN_ENV])


if __name__ == '__main__':
    Sharkling(fresh_run=True).run()
