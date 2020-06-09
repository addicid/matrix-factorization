import numba as nb
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator
from .utils import preprocess_data


@nb.njit()
def _sgd(
    X: np.ndarray,
    global_mean: float,
    user_biases: np.ndarray,
    item_biases: np.ndarray,
    n_epochs: int,
    lr: float,
    reg: float,
    verbose: int,
) -> (np.ndarray, np.ndarray):
    """
    Performs stochastic gradient descent to estimate the user_biases and item_biases

    Arguments:
        X {numpy array} -- User-item ranking matrix
        global_mean {float} -- Global mean of all ratings
        user_biases {numpy array} -- User biases vector of shape (n_users, 1)
        item_biases {numpy array} -- Item biases vector of shape (n_items, 1)
        n_epochs {int} -- Number of epochs to run
        lr {float} -- Learning rate alpha
        reg {float} -- Regularization parameter lambda for Frobenius norm
        verbose {int} -- Verbosity when fitting. 0 for nothing and 1 for printing epochs

    Returns:
        user_biases [np.ndarray] -- Updated user_biases vector
        item_biases [np.ndarray] -- Updated item_bases vector
    """

    for epoch in range(n_epochs):
        for i in range(X.shape[0]):
            user, item, rating = int(X[i, 0]), int(X[i, 1]), X[i, 2]

            # Compute error
            rating_pred = global_mean + user_biases[user] + item_biases[item]
            error = rating - rating_pred

            # Update parameters
            user_biases[user] += lr * (error - reg * user_biases[user])
            item_biases[item] += lr * (error - reg * item_biases[item])

        # Display fitting messages
        if verbose == 1:
            rmse = error ** 2
            print("Epoch ", epoch + 1, "/", n_epochs, " -  train_rmse:", rmse)

    return user_biases, item_biases


@nb.njit()
def _predict(
    X: np.ndarray,
    global_mean: float,
    min_rating: int,
    max_rating: int,
    user_biases: np.ndarray,
    item_biases: np.ndarray,
) -> (list, list):
    """
    Calculate predicted ratings for each user-item pair.

    Arguments:
        X {np.ndarray} -- Matrix with columns representing (user_id, item_id)
        global_mean {float} -- Global mean of all ratings
        min_rating {int} -- Lowest rating possible
        max_rating {int} -- Highest rating possible
        user_biases {np.ndarray} -- User biases vector of length n_users
        item_biases {np.ndarray} -- Item biases vector of length n_items

    Returns:
        predictions [np.ndarray] -- Vector containing rating predictions of all user, items in same order as input X
        predictions_possible [np.ndarray] -- Vector of whether both given user and item were contained in the data that the model was fitted on
    """

    predictions = []
    predictions_possible = []

    for i in range(X.shape[0]):
        user, item = int(X[i, 0]), int(X[i, 1])
        user_known = user != -1
        item_known = item != -1

        rating_pred = global_mean

        if user_known:
            rating_pred += user_biases[user]
        if item_known:
            rating_pred += item_biases[item]

        # Bound ratings to min and max rating range
        if rating_pred > max_rating:
            rating_pred = max_rating
        elif rating_pred < min_rating:
            rating_pred = min_rating

        predictions.append(rating_pred)
        predictions_possible.append(user_known and item_known)

    return predictions, predictions_possible


class BaselineModel(BaseEstimator):
    """
    Simple model which models the user item rating as r_{ui} = \mu + ubias_u + ibias_i which is sum of a global mean and the corresponding
    user and item biases. The global mean \mu is estimated as the mean of all ratings. The other parameters to be estimated ubias and ibias 
    are vectors of length n_users and n_items respectively. These two vectors are estimated using stochastic gradient descent on the RMSE 
    with regularization.

    Arguments:
        n_epochs {int} -- Number of epochs to train for (default: {100})
        reg {float} -- Lambda parameter for L2 regularization (default: {0.2})
        lr {float} -- Learning rate for gradient optimisation step (default: {0.005})
        min_rating {int} -- Smallest rating possible (default: {0})
        max_rating {int} -- Largest rating possible (default: {5})
        verbose {str} -- Verbosity when fitting. 0 to not print anything, 1 to print fitting model (default: {1})

    Attributes:
        n_users {int} -- Number of users
        n_items {int} -- Number of items
        global_mean {float} -- Global mean of all ratings
        user_biases {numpy array} -- User bias vector of shape (n_users, 1)
        item_biases {numpy array} -- Item bias vector of shape (n_items, i)
        _user_id_map {dict} -- Mapping of user ids to assigned integer ids
        _item_id_map {dict} -- Mapping of item ids to assigned integer ids
        _predictions_possible {list} -- Boolean vector of whether both user and item were known for prediction. Only available after calling predict
    """

    def __init__(
        self,
        n_epochs: int = 100,
        reg: float = 0.02,
        lr: float = 0.005,
        min_rating: int = 0,
        max_rating: int = 5,
        verbose=1,
    ):
        self.n_epochs = n_epochs
        self.reg = reg
        self.lr = lr
        self.min_rating = min_rating
        self.max_rating = max_rating
        self.verbose = verbose
        self.n_users, self.n_items = None, None
        self.global_mean = None
        self.user_biases, self.item_biases = None, None
        self._user_id_map, self._item_id_map = None, None
        return

    def fit(self, X: pd.DataFrame):
        """ Fits simple mean and bias model to given user item ratings

        Arguments:
            X {pandas DataFrame} -- Dataframe containing columns u_id, i_id and rating
        """
        X, self._user_id_map, self._item_id_map = preprocess_data(X)

        self.n_users = len(self._user_id_map)
        self.n_items = len(self._item_id_map)

        # Initialize parameters
        self.user_biases = np.zeros(self.n_users)
        self.item_biases = np.zeros(self.n_items)

        self.global_mean = X["rating"].mean()

        # Run stochastic gradient descent
        user_biases, item_biases = _sgd(
            X=X.to_numpy(),
            global_mean=self.global_mean,
            user_biases=self.user_biases,
            item_biases=self.item_biases,
            n_epochs=self.n_epochs,
            lr=self.lr,
            reg=self.reg,
            verbose=self.verbose,
        )

        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict ratings for given users and items

        Arguments:
            X {pd.DataFrame} -- Dataframe containing columns u_id and i_id

        Returns:
            predictions [np.ndarray] -- Vector containing rating predictions of all user, items in same order as input X
        """
        # Keep only required columns in given order
        X = X.loc[:, ["u_id", "i_id"]]

        # Remap user_id and item_id
        X.loc[:, "u_id"] = X["u_id"].map(self._user_id_map)
        X.loc[:, "i_id"] = X["i_id"].map(self._item_id_map)

        # Replace missing mappings with -1
        X.fillna(-1, inplace=True)

        # Get predictions
        predictions, predictions_possible = _predict(
            X=X.to_numpy(),
            global_mean=self.global_mean,
            min_rating=self.min_rating,
            max_rating=self.max_rating,
            user_biases=self.user_biases,
            item_biases=self.item_biases,
        )

        self._predictions_possible = predictions_possible

        return predictions