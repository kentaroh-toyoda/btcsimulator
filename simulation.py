#!/usr/bin/env python
# vim: set fileencoding=utf-8 :
#
# Author:   Kentaroh Toyoda
# Mail	:   toyoda@ohtsuki.ics.keio.ac.jp
# License:  MIT License
# Created:  2016-07-28
#

from btcsimulator.server.core import celery
from btcsimulator.server.core import logger
from btcsimulator.server.tasks import start_simulation_task


if __name__ == '__main__':
    days = 30
    type = 'selfish'
    miners = 3

    logger.info("Starting %d days %s simulation with %d miners" %(days, type, miners))
    # Start the simulation in the worker
    start_simulation_task.delay(miners, days, type)
