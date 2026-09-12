=============================
Contributing to pycargoebuild
=============================


Policy
======

This project is developed under the umbrella of `Gentoo Linux`_.
As such, it is bound by Gentoo policies, including but not limited to:

- `Gentoo Social Contract`_
- `Gentoo Code of Conduct`_
- `Gentoo Copyright Policy`_ (GLEP 76)
- `Gentoo AI Policy`_

TL;DR:

- be respectful
- do not use AI tools
- make sure you're legally allowed to submit anything you do under
  the project's license (GPL-2+)
- sign off your changes using your real name or an established online
  identity


The canonical repository
========================

The canonical `project repository`_ is hosted on git.gentoo.org,
as ``proj/pycargoebuild.git``.  The project repositories on Codeberg
and/or GitHub are read-only mirrors.


Reporting bugs
==============

Bugs should be reported to `Gentoo Bugzilla`_.  You can use the handy
URLs provided:

- `search for existing issues`_
- `report a bug / feature request`_
- `report a security issue`_

Please do not e-mail the maintainers or use Codeberg / GitHub comments
to report issues with commits.


Contributing
============

1. Do not use AI tools (why do I have to repeat that?!).  If you do,
   your code will be tainted and we won't be able to accept it.  And no,
   removing the label and pretending it's not slop won't help.

2. Before submitting a major contribution or behavior change, please
   report an issue and discuss your proposed changes first.  For minor
   bug fixes, submitting the change immediately is fine.

3. Please try to follow the existing coding style (preferably the one
   from newer commits, sorry about the mess).  When in doubt, do what's
   easier for you and we'll go from there.

4. Aim for clearly delineated commits with atomic changes and clear
   commit messages.  Follow the existing style.  Ensure that all
   significant information can be found in commits themselves, as pull
   request description / cover letter will be discarded.  Become friends
   with ``git rebase`` (see e.g. `git rebase in depth`_).

5. It's fine (and even preferable for bigger changes) to send
   work-in-progress changes for early feedback.  Do not hesitate to ask
   for suggestions or help.

6. If your changes aren't getting any attention, please ping us.  We may
   have missed them, we may have gotten distracted, or we may simply not
   have realized that they are ready.  Pinging on one of the `Gentoo IRC
   channels`_ can be especially helpful.

Changes can be submitted using:

- pull requests to the `GitHub mirror`_ (preferable)
- patches sent via e-mail to the maintainers
- patches attached to bug reports


.. _Gentoo Linux: https://www.gentoo.org/
.. _Gentoo Social Contract: https://www.gentoo.org/get-started/philosophy/social-contract.html
.. _Gentoo Code of Conduct: https://wiki.gentoo.org/wiki/Project:Council/Code_of_conduct
.. _Gentoo Copyright Policy: https://www.gentoo.org/glep/glep-0076.html
.. _Gentoo AI Policy: https://wiki.gentoo.org/wiki/Project:Council/AI_policy
.. _project repository: https://gitweb.gentoo.org/proj/pycargoebuild.git/
.. _Gentoo Bugzilla: https://bugs.gentoo.org/
.. _search for existing issues: https://bugs.gentoo.org/buglist.cgi?quicksearch=app-portage/pycargoebuild
.. _report a bug / feature request: https://bugs.gentoo.org/enter_bug.cgi?product=Gentoo+Linux&component=Current+packages&short_desc=dev-vcs/pycargoebuild:+
.. _report a security issue: https://bugs.gentoo.org/enter_bug.cgi?product=Gentoo+Security&component=Vulnerabilities&short_desc=dev-vcs/pycargoebuild:+
.. _git rebase in depth: https://git-rebase.io/
.. _Gentoo IRC channels: https://www.gentoo.org/get-involved/irc-channels/
.. _GitHub mirror: https://github.com/gentoo/pycargoebuild/
