from adminsortable2.admin import SortableInlineAdminMixin
from django.conf.urls import url
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.models import Q, TextField
from django.forms import ModelForm, ModelMultipleChoiceField
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _, ungettext
from reversion.admin import VersionAdmin

from django_ace import AceWidget
from judge.models import Assignment, AssignmentProblem, AssignmentSubmission, Profile, Rating, Submission
from judge.ratings import rate_assignment
from judge.utils.views import NoBatchDeleteMixin
from judge.widgets import AdminHeavySelect2MultipleWidget, AdminHeavySelect2Widget, AdminMartorWidget, \
    AdminSelect2MultipleWidget, AdminSelect2Widget


class AdminHeavySelect2Widget(AdminHeavySelect2Widget):
    @property
    def is_hidden(self):
        return False


class AssignmentTagForm(ModelForm):
    assignments = ModelMultipleChoiceField(
        label=_('Included assignments'),
        queryset=Assignment.objects.all(),
        required=False,
        widget=AdminHeavySelect2MultipleWidget(data_view='assignment_select2'))


class AssignmentTagAdmin(admin.ModelAdmin):
    fields = ('name', 'color', 'description', 'assignments')
    list_display = ('name', 'color')
    actions_on_top = True
    actions_on_bottom = True
    form = AssignmentTagForm
    formfield_overrides = {
        TextField: {'widget': AdminMartorWidget},
    }

    def save_model(self, request, obj, form, change):
        super(AssignmentTagAdmin, self).save_model(request, obj, form, change)
        obj.assignments.set(form.cleaned_data['assignments'])

    def get_form(self, request, obj=None, **kwargs):
        form = super(AssignmentTagAdmin, self).get_form(request, obj, **kwargs)
        if obj is not None:
            form.base_fields['assignments'].initial = obj.assignments.all()
        return form


class AssignmentProblemInlineForm(ModelForm):
    class Meta:
        widgets = {'problem': AdminHeavySelect2Widget(data_view='problem_select2')}


class AssignmentProblemInline(SortableInlineAdminMixin, admin.TabularInline):
    model = AssignmentProblem
    verbose_name = _('Problem')
    verbose_name_plural = 'Problems'
    fields = ('problem', 'points', 'partial', 'is_pretested', 'max_submissions', 'output_prefix_override', 'order',
              'rejudge_column')
    readonly_fields = ('rejudge_column',)
    form = AssignmentProblemInlineForm

    def rejudge_column(self, obj):
        if obj.id is None:
            return ''
        return format_html('<a class="button rejudge-link" href="{}">Rejudge</a>',
                           reverse('admin:judge_assignment_rejudge', args=(obj.assignment.id, obj.id)))
    rejudge_column.short_description = ''


class AssignmentForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super(AssignmentForm, self).__init__(*args, **kwargs)
        if 'rate_exclude' in self.fields:
            if self.instance and self.instance.id:
                self.fields['rate_exclude'].queryset = \
                    Profile.objects.filter(assignment_history__assignment=self.instance).distinct()
            else:
                self.fields['rate_exclude'].queryset = Profile.objects.none()
        self.fields['banned_users'].widget.can_add_related = False
        self.fields['view_assignment_scoreboard'].widget.can_add_related = False

    def clean(self):
        cleaned_data = super(AssignmentForm, self).clean()
        cleaned_data['banned_users'].filter(current_assignment__assignment=self.instance).update(current_assignment=None)

    class Meta:
        widgets = {
            'authors': AdminHeavySelect2MultipleWidget(data_view='profile_select2'),
            'curators': AdminHeavySelect2MultipleWidget(data_view='profile_select2'),
            'testers': AdminHeavySelect2MultipleWidget(data_view='profile_select2'),
            'private_assignmentants': AdminHeavySelect2MultipleWidget(data_view='profile_select2',
                                                                   attrs={'style': 'width: 100%'}),
            'organizations': AdminHeavySelect2MultipleWidget(data_view='organization_select2'),
            'tags': AdminSelect2MultipleWidget,
            'banned_users': AdminHeavySelect2MultipleWidget(data_view='profile_select2',
                                                            attrs={'style': 'width: 100%'}),
            'view_assignment_scoreboard': AdminHeavySelect2MultipleWidget(data_view='profile_select2',
                                                                       attrs={'style': 'width: 100%'}),
            'description': AdminMartorWidget(attrs={'data-markdownfy-url': reverse_lazy('assignment_preview')}),
        }


class AssignmentAdmin(NoBatchDeleteMixin, VersionAdmin):
    fieldsets = (
        (None, {'fields': ('key', 'name', 'authors', 'curators', 'testers')}),
        (_('Settings'), {'fields': ('is_visible', 'use_clarifications', 'hide_problem_tags', 'hide_problem_authors',
                                    'run_pretests_only', 'locked_after', 'scoreboard_visibility',
                                    'points_precision')}),
        (_('Scheduling'), {'fields': ('start_time', 'end_time', 'time_limit')}),
        (_('Details'), {'fields': ('description', 'og_image', 'logo_override_image', 'tags', 'summary')}),
        (_('Format'), {'fields': ('format_name', 'format_config', 'problem_label_script')}),
        (_('Rating'), {'fields': ('is_rated', 'rate_all', 'rating_floor', 'rating_ceiling', 'rate_exclude')}),
        (_('Access'), {'fields': ('access_code', 'is_private', 'private_assignmentants', 'is_organization_private',
                                  'organizations', 'view_assignment_scoreboard')}),
        (_('Justice'), {'fields': ('banned_users',)}),
    )
    list_display = ('key', 'name', 'is_visible', 'is_rated', 'locked_after', 'start_time', 'end_time', 'time_limit',
                    'user_count')
    search_fields = ('key', 'name')
    inlines = [AssignmentProblemInline]
    actions_on_top = True
    actions_on_bottom = True
    form = AssignmentForm
    change_list_template = 'admin/judge/assignment/change_list.html'
    filter_horizontal = ['rate_exclude']
    date_hierarchy = 'start_time'

    def get_actions(self, request):
        actions = super(AssignmentAdmin, self).get_actions(request)

        if request.user.has_perm('judge.change_assignment_visibility') or \
                request.user.has_perm('judge.create_private_assignment'):
            for action in ('make_visible', 'make_hidden'):
                actions[action] = self.get_action(action)

        if request.user.has_perm('judge.lock_assignment'):
            for action in ('set_locked', 'set_unlocked'):
                actions[action] = self.get_action(action)

        return actions

    def get_queryset(self, request):
        queryset = Assignment.objects.all()
        if request.user.has_perm('judge.edit_all_assignment'):
            return queryset
        else:
            return queryset.filter(Q(authors=request.profile) | Q(curators=request.profile)).distinct()

    def get_readonly_fields(self, request, obj=None):
        readonly = []
        if not request.user.has_perm('judge.assignment_rating'):
            readonly += ['is_rated', 'rate_all', 'rate_exclude']
        if not request.user.has_perm('judge.lock_assignment'):
            readonly += ['locked_after']
        if not request.user.has_perm('judge.assignment_access_code'):
            readonly += ['access_code']
        if not request.user.has_perm('judge.create_private_assignment'):
            readonly += ['is_private', 'private_assignmentants', 'is_organization_private', 'organizations']
            if not request.user.has_perm('judge.change_assignment_visibility'):
                readonly += ['is_visible']
        if not request.user.has_perm('judge.assignment_problem_label'):
            readonly += ['problem_label_script']
        return readonly

    def save_model(self, request, obj, form, change):
        # `is_visible` will not appear in `cleaned_data` if user cannot edit it
        if form.cleaned_data.get('is_visible') and not request.user.has_perm('judge.change_assignment_visibility'):
            if not form.cleaned_data['is_private'] and not form.cleaned_data['is_organization_private']:
                raise PermissionDenied
            if not request.user.has_perm('judge.create_private_assignment'):
                raise PermissionDenied

        super().save_model(request, obj, form, change)
        # We need this flag because `save_related` deals with the inlines, but does not know if we have already rescored
        self._rescored = False
        if form.changed_data and any(f in form.changed_data for f in ('format_config', 'format_name')):
            self._rescore(obj.key)
            self._rescored = True

        if form.changed_data and 'locked_after' in form.changed_data:
            self.set_locked_after(obj, form.cleaned_data['locked_after'])

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Only rescored if we did not already do so in `save_model`
        if not self._rescored and any(formset.has_changed() for formset in formsets):
            self._rescore(form.cleaned_data['key'])

    def has_change_permission(self, request, obj=None):
        if not request.user.has_perm('judge.edit_own_assignment'):
            return False
        if obj is None:
            return True
        return obj.is_editable_by(request.user)

    def _rescore(self, assignment_key):
        from judge.tasks import rescore_assignment
        transaction.on_commit(rescore_assignment.s(assignment_key).delay)

    def make_visible(self, request, queryset):
        if not request.user.has_perm('judge.change_assignment_visibility'):
            queryset = queryset.filter(Q(is_private=True) | Q(is_organization_private=True))
        count = queryset.update(is_visible=True)
        self.message_user(request, ungettext('%d assignment successfully marked as visible.',
                                             '%d assignments successfully marked as visible.',
                                             count) % count)
    make_visible.short_description = _('Mark assignments as visible')

    def make_hidden(self, request, queryset):
        if not request.user.has_perm('judge.change_assignment_visibility'):
            queryset = queryset.filter(Q(is_private=True) | Q(is_organization_private=True))
        count = queryset.update(is_visible=True)
        self.message_user(request, ungettext('%d assignment successfully marked as hidden.',
                                             '%d assignments successfully marked as hidden.',
                                             count) % count)
    make_hidden.short_description = _('Mark assignments as hidden')

    def set_locked(self, request, queryset):
        for row in queryset:
            self.set_locked_after(row, timezone.now())
        count = queryset.count()
        self.message_user(request, ungettext('%d assignment successfully locked.',
                                             '%d assignments successfully locked.',
                                             count) % count)
    set_locked.short_description = _('Lock assignment submissions')

    def set_unlocked(self, request, queryset):
        for row in queryset:
            self.set_locked_after(row, None)
        count = queryset.count()
        self.message_user(request, ungettext('%d assignment successfully unlocked.',
                                             '%d assignments successfully unlocked.',
                                             count) % count)
    set_unlocked.short_description = _('Unlock assignment submissions')

    def set_locked_after(self, assignment, locked_after):
        with transaction.atomic():
            assignment.locked_after = locked_after
            assignment.save()
            Submission.objects.filter(assignment_object=assignment,
                                      assignment__participation__virtual=0).update(locked_after=locked_after)

    def get_urls(self):
        return [
            url(r'^rate/all/$', self.rate_all_view, name='judge_assignment_rate_all'),
            url(r'^(\d+)/rate/$', self.rate_view, name='judge_assignment_rate'),
            url(r'^(\d+)/judge/(\d+)/$', self.rejudge_view, name='judge_assignment_rejudge'),
        ] + super(AssignmentAdmin, self).get_urls()

    def rejudge_view(self, request, assignment_id, problem_id):
        queryset = AssignmentSubmission.objects.filter(problem_id=problem_id).select_related('submission')
        for model in queryset:
            model.submission.judge(rejudge=True)

        self.message_user(request, ungettext('%d submission was successfully scheduled for rejudging.',
                                             '%d submissions were successfully scheduled for rejudging.',
                                             len(queryset)) % len(queryset))
        return HttpResponseRedirect(reverse('admin:judge_assignment_change', args=(assignment_id,)))

    def rate_all_view(self, request):
        if not request.user.has_perm('judge.assignment_rating'):
            raise PermissionDenied()
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('TRUNCATE TABLE `%s`' % Rating._meta.db_table)
            Profile.objects.update(rating=None)
            for assignment in Assignment.objects.filter(is_rated=True, end_time__lte=timezone.now()).order_by('end_time'):
                rate_assignment(assignment)
        return HttpResponseRedirect(reverse('admin:judge_assignment_changelist'))

    def rate_view(self, request, id):
        if not request.user.has_perm('judge.assignment_rating'):
            raise PermissionDenied()
        assignment = get_object_or_404(Assignment, id=id)
        if not assignment.is_rated or not assignment.ended:
            raise Http404()
        with transaction.atomic():
            assignment.rate()
        return HttpResponseRedirect(request.META.get('HTTP_REFERER', reverse('admin:judge_assignment_changelist')))

    def get_form(self, request, obj=None, **kwargs):
        form = super(AssignmentAdmin, self).get_form(request, obj, **kwargs)
        if 'problem_label_script' in form.base_fields:
            # form.base_fields['problem_label_script'] does not exist when the user has only view permission
            # on the model.
            form.base_fields['problem_label_script'].widget = AceWidget('lua', request.profile.ace_theme)

        perms = ('edit_own_assignment', 'edit_all_assignment')
        form.base_fields['curators'].queryset = Profile.objects.filter(
            Q(user__is_superuser=True) |
            Q(user__groups__permissions__codename__in=perms) |
            Q(user__user_permissions__codename__in=perms),
        ).distinct()
        return form


class AssignmentParticipationForm(ModelForm):
    class Meta:
        widgets = {
            'assignment': AdminSelect2Widget(),
            'user': AdminHeavySelect2Widget(data_view='profile_select2'),
        }


class AssignmentParticipationAdmin(admin.ModelAdmin):
    fields = ('assignment', 'user', 'real_start', 'virtual', 'is_disqualified')
    list_display = ('assignment', 'username', 'show_virtual', 'real_start', 'score', 'cumtime', 'tiebreaker')
    actions = ['recalculate_results']
    actions_on_bottom = actions_on_top = True
    search_fields = ('assignment__key', 'assignment__name', 'user__user__username')
    form = AssignmentParticipationForm
    date_hierarchy = 'real_start'

    def get_queryset(self, request):
        return super(AssignmentParticipationAdmin, self).get_queryset(request).only(
            'assignment__name', 'assignment__format_name', 'assignment__format_config',
            'user__user__username', 'real_start', 'score', 'cumtime', 'tiebreaker', 'virtual',
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if form.changed_data and 'is_disqualified' in form.changed_data:
            obj.set_disqualified(obj.is_disqualified)

    def recalculate_results(self, request, queryset):
        count = 0
        for participation in queryset:
            participation.recompute_results()
            count += 1
        self.message_user(request, ungettext('%d participation recalculated.',
                                             '%d participations recalculated.',
                                             count) % count)
    recalculate_results.short_description = _('Recalculate results')

    def username(self, obj):
        return obj.user.username
    username.short_description = _('username')
    username.admin_order_field = 'user__user__username'

    def show_virtual(self, obj):
        return obj.virtual or '-'
    show_virtual.short_description = _('virtual')
    show_virtual.admin_order_field = 'virtual'

