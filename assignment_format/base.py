from abc import ABCMeta, abstractmethod, abstractproperty

from django.utils import six


class abstractclassmethod(classmethod):
    __isabstractmethod__ = True

    def __init__(self, callable):
        callable.__isabstractmethod__ = True
        super(abstractclassmethod, self).__init__(callable)


class BaseAssignmentFormat(six.with_metaclass(ABCMeta)):
    @abstractmethod
    def __init__(self, assignment, config):
        self.config = config
        self.assignment = assignment

    @abstractproperty
    def name(self):
        """
        Name of this assignment format. Should be invoked with gettext_lazy.

        :return: str
        """
        raise NotImplementedError()

    @abstractclassmethod
    def validate(cls, config):
        """
        Validates the assignment format configuration.

        :param config: A dictionary containing the configuration for this assignment format.
        :return: None
        :raises: ValidationError
        """
        raise NotImplementedError()

    @abstractmethod
    def update_participation(self, participation):
        """
        Updates a AssignmentParticipation object's score, cumtime, and format_data fields based on this assignment format.
        Implementations should call AssignmentParticipation.save().

        :param participation: A AssignmentParticipation object.
        :return: None
        """
        raise NotImplementedError()

    @abstractmethod
    def display_user_problem(self, participation, assignment_problem):
        """
        Returns the HTML fragment to show a user's performance on an individual problem. This is expected to use
        information from the format_data field instead of computing it from scratch.

        :param participation: The AssignmentParticipation object linking the user to the assignment.
        :param assignment_problem: The AssignmentProblem object representing the problem in question.
        :return: An HTML fragment, marked as safe for Jinja2.
        """
        raise NotImplementedError()

    @abstractmethod
    def display_participation_result(self, participation):
        """
        Returns the HTML fragment to show a user's performance on the whole assignment. This is expected to use
        information from the format_data field instead of computing it from scratch.

        :param participation: The AssignmentParticipation object.
        :return: An HTML fragment, marked as safe for Jinja2.
        """
        raise NotImplementedError()

    @abstractmethod
    def get_problem_breakdown(self, participation, assignment_problems):
        """
        Returns a machine-readable breakdown for the user's performance on every problem.

        :param participation: The AssignmentParticipation object.
        :param assignment_problems: The list of AssignmentProblem objects to display performance for.
        :return: A list of dictionaries, whose content is to be determined by the assignment system.
        """
        raise NotImplementedError()

    @abstractmethod
    def get_label_for_problem(self, index):
        """
        Returns the problem label for a given zero-indexed index.

        :param index: The zero-indexed problem index.
        :return: A string, the problem label.
        """
        raise NotImplementedError()

    @classmethod
    def best_solution_state(cls, points, total):
        if not points:
            return 'failed-score'
        if points == total:
            return 'full-score'
        return 'partial-score'

