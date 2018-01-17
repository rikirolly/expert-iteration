import numpy as np
import threading
import queue
from typing import TypeVar, Generic, List, Tuple
from .game import State, play_game, play_games
from .model import Model
from . import mcts
from . import utils

_example_search_size = 20

BoardState = TypeVar('BoardState')

class Trainer(Generic[BoardState]):
    def __init__(self,
                 model: Model[BoardState],
                 num_iterations: int,
                 iteration_size: int = 100,
                 search_size: int = 100) -> None:
        self.model = model
        self.game = self.model.game
        self.num_iterations = num_iterations
        self.iteration_size = iteration_size
        self.search_size = search_size

    def train_player(self):
        play_example_game = lambda: mcts.play_self(self.game, self.model.train_evaluator, _example_search_size)
        example_games = [play_example_game()]

        for i in range(1, self.num_iterations + 1):
            example_games.append(play_example_game())
            self.model.add_data(self.play_games())
            self.model.train()

            if self.train_is_better():
                self.model.new_checkpoint()
            else:
                self.model.restore_checkpoint()

            print('finished step %d' % i)

        example_games.append(play_example_game())

        return example_games

    def train_is_better(self):
        tot_games = 10
        reward = 0
        best_alg = mcts.Algorithm(self.game, self.model.best_evaluator, self.search_size)
        train_alg = mcts.Algorithm(self.game, self.model.train_evaluator, self.search_size)

        for i in range(tot_games):
            games = play_games(tot_games, self.game, [({0}, best_alg), ({1}, train_alg)])
            results = utils.unzip(games)[1]
            reward += sum([ mcts.rewards_from_result(result)[1] for result in results ])
        for i in range(tot_games):
            games = play_games(tot_games, self.game, [({0}, train_alg), ({1}, best_alg)])
            results = utils.unzip(games)[1]
            reward += sum([ mcts.rewards_from_result(result)[0] for result in results ])

        avg_reward = reward / (2 * tot_games)
        print(avg_reward)
        return avg_reward > 0.1


    def play_games(self) -> List[Tuple[State[BoardState], np.ndarray, np.ndarray]]:
        work_q = queue.Queue() #type: ignore
        result_q = queue.Queue() #type: ignore
        go = queue.Queue() #type: ignore
        alive = [self.iteration_size]
        in_q = [0]
        counter_lock = threading.Lock()

        def mp_play_self():
            my_q = queue.Queue()

            def eval_state(state: State[BoardState]) -> Tuple[np.ndarray, np.ndarray]:
                with counter_lock:
                    work_q.put((state, my_q))
                    in_q[0] += 1
                    if alive[0] == in_q[0]:
                        go.put(True)
                return my_q.get()

            result = mcts.play_self(self.game, mcts.Evaluator(eval_state=eval_state), self.search_size, 1.0)
            with counter_lock:
                alive[0] -= 1
                result_q.put(result)
                if alive[0] == 0:
                    go.put(False)
                elif alive[0] == in_q[0]:
                    go.put(True)

        for _ in range(self.iteration_size):
            threading.Thread(target=mp_play_self).start()

        while go.get():
            with counter_lock:
                ret_qs = []
                states = []
                for _ in range(in_q[0]):
                    state, ret_q = work_q.get_nowait()
                    ret_qs.append(ret_q)
                    states.append(state)
                in_q[0] = 0
                if len(states) > 0:
                    probs, values = self.model.eval_states(states, using=Model.PARAMS_BEST)
                    for ret_q, prob, value in zip(ret_qs, probs, values):
                        ret_q.put((prob, value))

        positions: List[Tuple[State[BoardState], np.ndarray, np.ndarray]] = []
        while not result_q.empty():
            positions += result_q.get_nowait()
        return positions
