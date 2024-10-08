#!/usr/bin/env python3
"""
Computes the total log probability of the sequences of tokens in each file,
according to a given smoothed trigram model.
"""
import argparse
import logging
import math
from pathlib import Path
import torch
import numpy as np
from sympy.physics.units import percent

from probs import Wordtype, LanguageModel, num_tokens, read_trigrams

log = logging.getLogger(Path(__file__).stem)  # For usage, see findsim.py in earlier assignment.


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "model1",
        type=Path,
        help="path to the first trained model",
    )
    parser.add_argument(
        "model2",
        type=Path,
        help="path to the second trained model",
    )
    parser.add_argument(
        "prior_prob",
        type=float,
        help="prior prob of category in first trained model",
    )
    parser.add_argument(
        "test_files",
        type=Path,
        nargs="*"
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cpu",
        choices=['cpu', 'cuda', 'mps'],
        help="device to use for PyTorch (cpu or cuda, or mps if you are on a mac)"
    )

    # for verbosity of logging
    parser.set_defaults(logging_level=logging.INFO)
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v", "--verbose", dest="logging_level", action="store_const", const=logging.DEBUG
    )
    verbosity.add_argument(
        "-q", "--quiet", dest="logging_level", action="store_const", const=logging.WARNING
    )

    return parser.parse_args()


def file_log_prob(file: Path, lm: LanguageModel) -> float:
    """The file contains one sentence per line. Return the total
    log-probability of all these sentences, under the given language model.
    (This is a natural log, as for all our internal computations.)
    """
    log_prob = 0.0

    x: Wordtype;
    y: Wordtype;
    z: Wordtype  # type annotation for loop variables below
    for (x, y, z) in read_trigrams(file, lm.vocab):
        log_prob += lm.log_prob(x, y, z)  # log p(z | xy)

        # If the factor p(z | xy) = 0, then it will drive our cumulative file
        # probability to 0 and our cumulative log_prob to -infinity.  In
        # this case we can stop early, since the file probability will stay
        # at 0 regardless of the remaining tokens.
        if log_prob == -math.inf: break

        # Why did we bother stopping early?  It could occasionally
        # give a tiny speedup, but there is a more subtle reason -- it
        # avoids a ZeroDivisionError exception in the unsmoothed case.
        # If xyz has never been seen, then perhaps yz hasn't either,
        # in which case p(next token | yz) will be 0/0 if unsmoothed.
        # We can avoid having Python attempt 0/0 by stopping early.
        # (Conceptually, 0/0 is an indeterminate quantity that could
        # have any value, and clearly its value doesn't matter here
        # since we'd just be multiplying it by 0.)

    return log_prob


# def main():
#     args = parse_args()
#     print(args.model1)
#     print(args.model2)
#     print(args.prior_prob)
#     print(args.test_files)

def main():
    args = parse_args()
    logging.basicConfig(level=args.logging_level)

    # Specify hardware device where all tensors should be computed and
    # stored.  This will give errors unless you have such a device
    # (e.g., 'gpu' will work in a Kaggle Notebook where you have
    # turned on GPU acceleration).
    if args.device == 'mps':
        if not torch.backends.mps.is_available():
            if not torch.backends.mps.is_built():
                logging.critical("MPS not available because the current PyTorch install was not "
                                 "built with MPS enabled.")
            else:
                logging.critical("MPS not available because the current MacOS version is not 12.3+ "
                                 "and/or you do not have an MPS-enabled device on this machine.")
            exit(1)
    torch.set_default_device(args.device)

    log.info("Testing...")
    lm1 = LanguageModel.load(args.model1, device=args.device)
    lm2 = LanguageModel.load(args.model2, device=args.device)
    assert lm1.vocab == lm2.vocab

    # We use natural log for our internal computations and that's
    # the kind of log-probability that file_log_prob returns.
    # We'll print that first.

    log.info("Per-file log-probabilities:")
    total_log_prob = 0.0
    total_n_of_cat1_files = 0
    max_difference = -np.inf
    min_difference = np.inf
    for file in args.test_files:
        print("for file:", file)
        log_prob1: float = file_log_prob(file, lm1)
        log_prob2: float = file_log_prob(file, lm2)
        log_prob1 += np.log(args.prior_prob)
        log_prob2 += np.log(1-args.prior_prob)
        predicted_model = args.model1 if log_prob1>=log_prob2 else args.model2
        print(f"{str(predicted_model):<20}{str(file):<20}")
        total_n_of_cat1_files += 1 if log_prob1>=log_prob2 else 0
        difference = log_prob1 - log_prob2
        max_difference = difference if difference>max_difference else max_difference
        min_difference = difference if difference<min_difference else min_difference
        # print(log_prob1)
        # print(log_prob2)
        # print(f"{log_prob:g}\t{file}")
        # total_log_prob += log_prob

    max_likelihood_ratio = np.exp(max_difference)
    min_likelihood_ratio = np.exp(min_difference)
    percent1 = round(total_n_of_cat1_files/len(args.test_files)*100,2)
    percent2 = round((len(args.test_files) - total_n_of_cat1_files) / len(args.test_files) * 100, 2)
    print(f"{total_n_of_cat1_files:<6}files were more probable {str(args.model1):12}({percent1:<5}%)")
    print(f"{len(args.test_files)-total_n_of_cat1_files:<6}files were more probable {str(args.model2):12}({percent2:<5}%)")
    print(f"max log prob difference is {max_difference}")
    print(f"min log prob difference is {min_difference}")
    print(f"max likelihood ratio is {max_likelihood_ratio}")
    print(f"min likelihood ratio is {min_likelihood_ratio}")
    # But cross-entropy is conventionally measured in bits: so when it's
    # time to print cross-entropy, we convert log base e to log base 2,
    # by dividing by log(2).

    # bits = -total_log_prob / math.log(2)  # convert to bits of surprisal

    # We also divide by the # of tokens (including EOS tokens) to get
    # bits per token.  (The division happens within the print statement.)

    # tokens = sum(num_tokens(test_file) for test_file in args.test_files)
    # print(f"Overall cross-entropy:\t{bits / tokens:.5f} bits per token")

if __name__ == "__main__":
    main()

