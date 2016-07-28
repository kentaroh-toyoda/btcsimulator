__author__ = 'victor'
import numpy
import simpy
from block import Block, sha256
from persistence import *
from network import Socket, Link, Event

class Miner(object):

    # Define action names
    BLOCK_REQUEST = 1 # Hey! I need a block!
    BLOCK_RESPONSE = 2 # Here is the block you wanted!
    HEAD_NEW = 3 # I have a new chain head!
    BLOCK_NEW = 4 # Just mined a new block!

    # Network block rate a.k.a 1 block every ten minutes
    BLOCK_RATE = 1.0 / 600.0

    # Block size is now 1MB.
    BLOCK_SIZE = 1000

    # A miner is able to verify 200KBytes per seconds
    VERIFY_RATE = 200 * 1024

    def __init__(self, env, store, hashrate, verifyrate, seed_block):
        # Simulation environment
        self.env = env
        # Get miner id from redis
        self.id = self.get_id()
        # Socket
        self.socket = Socket(env, store, self.id)
        # Miner computing percentage of total network
        self.hashrate = hashrate
        # Miner block verification rate
        self.verifyrate = verifyrate
        # Store seed block
        self.seed_block = seed_block
        # Pointer to the block chain head
        self.chain_head = '*'
        # Hash with all the blocks the miner knows about
        self.blocks = dict()
        # Array with blocks needed to be processed
        self.blocks_new = []
        # Create event to notify when a block is mined
        self.block_mined = env.event()
        # Create event to notify when a new block arrives
        self.block_received = env.event()
        # Create event to notify when the mining process can continue
        self.continue_mining = env.event()
        self.mining = None
        # Store the miner in the database
        self.store()
        self.total_blocks = 0

    def get_id(self):
        return get_id("miners")

    def store(self):
        key = "miners:" + str(self.id)
        r.hmset(key, {"hashrate": self.hashrate / Miner.BLOCK_RATE, "verifyrate": self.verifyrate})
        r.sadd("miners", self.id)


    def start(self):
        # Add the seed_block
        self.add_block(self.seed_block)
        # Start the process of adding blocks
        self.env.process(self.wait_for_new_block())
        # Receive network events
        self.env.process(self.receive_events())
        # Start mining and store the process so it can be interrupted
        self.mining = self.env.process(self.mine_block())

    def mine_block(self):
        # Indefinitely mine new blocks
        while True:
            try:
                # Determine block size
                block_size = 1024 * BLOCK_SIZE * numpy.random.random()
                # Determine the time the block will be mined depending on the miner hashrate
                time = numpy.random.exponential(1/self.hashrate, 1)[0]
                # Wait for the block to be mined
                yield self.env.timeout(time)
                # Once the block is mined it needs to be added. An event is triggered
                block = Block(self.chain_head, self.blocks[self.chain_head].height + 1, self.env.now, self.id, block_size, 1)
                self.notify_new_block(block)
            except simpy.Interrupt as i:
                # When the mining process is interrupted it cannot continue until it is told to continue
                yield self.continue_mining

    def notify_new_block(self, block):
        self.total_blocks += 1
        #print("%d \tI just mined a block at %7.4f" % (self.id, self.env.now))
        self.block_mined.succeed(block)
        # Create a new mining event
        self.block_mined = self.env.event()

    def notify_received_block(self, block):
        self.block_received.succeed(block)
        # Create a new block received event
        self.block_received = self.env.event()

    def stop_mining(self):
        self.mining.interrupt()

    def keep_mining(self):
        self.continue_mining.succeed()
        self.continue_mining = self.env.event()

    def add_block(self, block):
        # Add the seed block to the known blocks
        self.blocks[sha256(block)] = block
        # Store the block in redis
        r.zadd("miners:" + str(self.id) + ":blocks", block.height, sha256(block))
        # Announce block if chain_head isn't empty
        if self.chain_head == "*":
            self.chain_head = sha256(block)
        # If block height is greater than chain head, update chain head and announce new head
        if (block.height > self.blocks[self.chain_head].height):
            self.chain_head = sha256(block)
            self.announce_block(block)

    def wait_for_new_block(self):
        while True:
            # Wait for a block to be mined or received
            blocks = yield self.block_mined | self.block_received
            # Interrupt the mining process so the block can be added
            self.stop_mining()
            #print("%d \tI stop mining" % self.id)
            for event, block in blocks.items():
                #print("Miner %d - mined block at %7.4f" %(self.id, self.env.now))
                # Add the new block to the pending ones
                self.blocks_new.append(block)
                # Process new blocks
            yield self.env.process(self.process_new_blocks())
            # Keep mining
            self.keep_mining()

    def verify_block(self, block):
        # If block was mined by the miner but the previous block is not the chain head it will not be valid
        if block.miner_id == self.id and block.prev != self.chain_head:
            return -1
        # If the previous block is not in miner blocks it is not possible to validate current block
        if block.prev not in self.blocks:
            return 0
        # If block height isn't previous block + 1 it will not be valid
        if block.height != self.blocks[block.prev].height + 1:
            return -1
        return 1

    def process_new_blocks(self):
        blocks_later = []
        # Validate every new block
        for block in self.blocks_new:
            # Block validation takes some time
            yield self.env.timeout(block.size / self.verifyrate)
            valid = self.verify_block(block)
            if valid == 1:
                self.add_block(block)
            elif valid == 0:
                #Logger.log(self.env.now, self.id, "NEED_DATA", sha256(block))
                self.request_block(block.prev)
                blocks_later.append(block)
        self.blocks_new = blocks_later

    # Announce new head when block is added to the chain
    def announce_block(self, block):
        if self.id == 8:
            print("Announce %s - %s" %(block, self.blocks[block].miner_id))
        self.broadcast(Miner.HEAD_NEW, sha256(block))

    # Request a block to all links
    def request_block(self, block, to=None):
        #Logger.log(self.env.now, self.id, "REQUEST", block)
        if to is None:
            self.broadcast(Miner.BLOCK_REQUEST, block)
        else:
            self.send_event(to, Miner.BLOCK_REQUEST, block)

    # Send a block to a specific miner
    def send_block(self, block_hash, to):
        # Find the block
        block = self.blocks[block_hash]
        # Send the event
        self.send_event(to, Miner.BLOCK_RESPONSE, block)

    # Send certain event to a specific miner
    def send_event(self, to, action, payload):
        self.socket.send_event(to, action, payload)

    # Broadcast an event to all links
    def broadcast(self, action, payload):
        self.socket.broadcast(action, payload)

    def receive_events(self):
        while True:
            # Wait for a network event
            if len(self.socket.links) == 0:
                return
            data = yield self.socket.receive(self.id)
            if data.action == Miner.BLOCK_REQUEST:
                # Send block if we have it
                if data.payload in self.blocks:
                    self.send_block(data.payload, data.origin)
            elif data.action == Miner.BLOCK_RESPONSE:
                self.notify_received_block(data.payload)
            elif data.action == Miner.HEAD_NEW:
                # If we don't have the new head, we need to request it
                if data.payload not in self.blocks:
                    self.request_block(data.payload)

            #print("Miner %d - receives block %d at %7.4f" %(self.id, sha256(data), self.env.now))

    def add_link(self, destination, delay):
        link = Link(self.id, destination, delay)
        self.socket.add_link(link)
        r.sadd("miners:" + str(self.id) + ":links", link.id)

    @staticmethod
    def connect(miner, other_miner):
        miner.add_link(other_miner.id, 0.02)
        other_miner.add_link(miner.id, 0.02)


class BadMiner(Miner):

    # A bad miner (with more than 50% of network computing power
    # will ignore all blocks no mine by self
    def add_block(self, block):
        # Add the block to the known blocks
        self.blocks[sha256(block)] = block
        # Store the block in redis
        r.zadd("miners:" + str(self.id) + ":blocks", block.height, sha256(block))
        # Announce block if chain_head isn't empty
        if self.chain_head == "*":
            self.chain_head = sha256(block)
        # Ignore all blocks that are not mined by the bad miner
        if block.miner_id != self.id:
            return
        # If block height is greater than chain head, update chain head and announce new head
        if block.height > self.blocks[self.chain_head].height:
            self.chain_head = sha256(block)
            self.announce_block(block)


class SelfishMiner(Miner):

    # A selfish miner
    def __init__(self, env, store, hashrate, verifyrate, seed_block):
        self.chain_head_others = "*"
        self.private_branch_len = 0
        super(SelfishMiner, self).__init__( env, store, hashrate, verifyrate, seed_block)

    def add_block(self, block):
        # Save block
        self.blocks[sha256(block)] = block
        if self.chain_head == "*":
            self.chain_head = sha256(block)
            self.chain_head_others = sha256(block)
            return
        if (block.miner_id == self.id) and (block.height > self.blocks[self.chain_head].height):
            delta_prev = self.blocks[self.chain_head].height - self.blocks[self.chain_head_others].height
            self.chain_head = sha256(block)
            self.private_branch_len += 1
            if (delta_prev == 0) and (self.private_branch_len == 2):
                self.announce_block(self.chain_head)
                self.private_branch_len = 0

        if (block.miner_id != self.id) and (block.height > self.blocks[self.chain_head_others].height):
            delta_prev = self.blocks[self.chain_head].height - self.blocks[self.chain_head_others].height
            self.chain_head_others = sha256(block)
            if delta_prev <= 0:
                self.chain_head = sha256(block)
                self.private_branch_len = 0
            elif delta_prev == 1:
                self.announce_block(self.chain_head)
            elif delta_prev == 2:
                self.announce_block(self.chain_head)
                self.private_branch_len = 0
            else:
                iter_hash = self.chain_head
                temp = 0
                print(delta_prev)
                if delta_prev >= 6:
                    temp = 1
                while self.blocks[iter_hash].height != block.height + temp:
                    iter_hash = self.blocks[iter_hash].prev
                self.announce_block(iter_hash)

