#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/22 01:51:02.660072
Revised: 2026/11/22 01:51:02.660072

Wording of the moderation e-mails, in every app language (the languages of
renar-frontend's i18n/translations.py: English, Galician, Portuguese,
Spanish and Esperanto). English is the fallback for any other code.

Keys:
- ``subject_user`` / ``subject_reporter``: the subjects.
- ``hello``: the greeting, with ``{username}``.
- ``action.<ModerationAction>``: what was done (user statements only);
  ``username_reset`` takes ``{new_username}``.
- ``reason.<ModerationReason>``: why, naming the rule of the Terms.
- ``report.<comment|review|profile>``: a reporter's intro, with ``{author}``.
- ``outcome.<removed|restricted|none>``: what happened to a report.
- the rest: fixed lines of the statement.

Over the 200-line review size on purpose: it is data only, one table per
language, and every wording change touches all of them together.
"""

_TERMS = {
    "en": "Terms of Service, Acceptable use",
    "gl": "Termos do servizo, Uso aceptable",
    "pt": "Termos de Serviço, Utilização aceitável",
    "es": "Términos del servicio, Uso aceptable",
    "eo": "Servaj Kondiĉoj, Akceptebla uzo",
}

EN = {
    "subject_user": "Renar: a moderation decision about your account",
    "subject_reporter": "Renar: the outcome of your report",
    "hello": "Hello {username},",
    "action.comment_removed": "We removed one of your comments.",
    "action.review_removed": "We removed one of your reviews.",
    "action.account_suspended": "We suspended your account. You can't sign in until the suspension is lifted.",
    "action.account_closed": "We closed your account and deleted its data.",
    "action.username_reset": "We changed your username. Your new username is {new_username}.",
    "action.review_rights_withdrawn": "We withdrew your ability to post reviews.",
    "content_label": "The content concerned:",
    "reason_label": "Why:",
    "note_label": "Moderator's note:",
    "from_report_yes": "This decision followed a report from another user.",
    "from_report_no": "We took this decision on our own initiative.",
    "automated": "No automated means were used to detect the content or to take this decision.",
    "contest": (
        "You can contest this decision by writing to legal@renar.app within 6 months. A person will "
        "review it again and reply with a reasoned decision. You can also go to court."
    ),
    "reason.illegal_content": "The content is illegal.",
    "reason.no_rights": f"It is content you don't have the right to share ({_TERMS['en']}).",
    "reason.harassment": f"It harasses, threatens, insults or impersonates others ({_TERMS['en']}).",
    "reason.hate_or_violence": f"It is hate speech, or incites violence or self-harm ({_TERMS['en']}).",
    "reason.child_sexual_content": f"It is sexual content involving minors ({_TERMS['en']}; also illegal).",
    "reason.spam": f"It is spam or advertising, or part of creating accounts in bulk ({_TERMS['en']}).",
    "reason.circumvention": (
        f"It circumvents rate limits, invite gating, blocks or other anti-abuse measures ({_TERMS['en']})."
    ),
    "reason.scraping": f"It uses automated means to scrape or bulk-extract data ({_TERMS['en']}).",
    "reason.disruption": f"It interferes with the service or with other users' access to it ({_TERMS['en']}).",
    "reason.no_breach": "We found no breach of the law or of the Terms of Service.",
    "report.comment": "Thank you for your report about a comment by {author}.",
    "report.review": "Thank you for your report about a review by {author}.",
    "report.profile": "Thank you for your report about the profile of {author}.",
    "outcome.removed": "We reviewed it and removed the content.",
    "outcome.restricted": "We reviewed it and restricted the account.",
    "outcome.none": "We reviewed it and took no action.",
    "contest_reporter": (
        "If you disagree, you can contest this decision by writing to legal@renar.app within 6 months. "
        "A person will review it again. You can also go to court."
    ),
    "signature": "The Renar team",
}

GL = {
    "subject_user": "Renar: unha decisión de moderación sobre a túa conta",
    "subject_reporter": "Renar: o resultado da túa denuncia",
    "hello": "Ola, {username}:",
    "action.comment_removed": "Eliminamos un dos teus comentarios.",
    "action.review_removed": "Eliminamos unha das túas recensións.",
    "action.account_suspended": "Suspendemos a túa conta. Non poderás iniciar sesión ata que se levante a suspensión.",
    "action.account_closed": "Pechamos a túa conta e borramos os seus datos.",
    "action.username_reset": "Cambiamos o teu nome de usuario. O novo é {new_username}.",
    "action.review_rights_withdrawn": "Retiramos a túa posibilidade de publicar recensións.",
    "content_label": "O contido afectado:",
    "reason_label": "Motivo:",
    "note_label": "Nota do moderador:",
    "from_report_yes": "Esta decisión tomouse a raíz dunha denuncia doutro usuario.",
    "from_report_no": "Tomamos esta decisión por iniciativa propia.",
    "automated": "Non se usaron medios automatizados para detectar o contido nin para tomar esta decisión.",
    "contest": (
        "Podes recorrer esta decisión escribindo a legal@renar.app nun prazo de 6 meses. Unha persoa "
        "revisaraa de novo e responderache cunha decisión motivada. Tamén podes acudir aos tribunais."
    ),
    "reason.illegal_content": "O contido é ilegal.",
    "reason.no_rights": f"É contido que non tes dereito a compartir ({_TERMS['gl']}).",
    "reason.harassment": f"Acosa, ameaza, insulta ou suplanta a outras persoas ({_TERMS['gl']}).",
    "reason.hate_or_violence": f"É discurso de odio ou incita á violencia ou a autolesionarse ({_TERMS['gl']}).",
    "reason.child_sexual_content": f"É contido sexual que implica a menores ({_TERMS['gl']}; ademais é ilegal).",
    "reason.spam": f"É spam ou publicidade, ou parte da creación masiva de contas ({_TERMS['gl']}).",
    "reason.circumvention": (
        f"Elude os límites de uso, os convites, os bloqueos ou outras medidas contra o abuso ({_TERMS['gl']})."
    ),
    "reason.scraping": f"Usa medios automatizados para extraer datos de forma masiva ({_TERMS['gl']}).",
    "reason.disruption": f"Interfire no funcionamento do servizo ou no acceso doutros usuarios ({_TERMS['gl']}).",
    "reason.no_breach": "Non atopamos ningún incumprimento da lei nin dos Termos do servizo.",
    "report.comment": "Grazas pola túa denuncia sobre un comentario de {author}.",
    "report.review": "Grazas pola túa denuncia sobre unha recensión de {author}.",
    "report.profile": "Grazas pola túa denuncia sobre o perfil de {author}.",
    "outcome.removed": "Revisámola e eliminamos o contido.",
    "outcome.restricted": "Revisámola e restrinximos a conta.",
    "outcome.none": "Revisámola e non tomamos ningunha medida.",
    "contest_reporter": (
        "Se non estás de acordo, podes recorrer esta decisión escribindo a legal@renar.app nun prazo de "
        "6 meses. Unha persoa revisaraa de novo. Tamén podes acudir aos tribunais."
    ),
    "signature": "O equipo de Renar",
}

PT = {
    "subject_user": "Renar: uma decisão de moderação sobre a sua conta",
    "subject_reporter": "Renar: o resultado da sua denúncia",
    "hello": "Olá, {username}:",
    "action.comment_removed": "Removemos um dos seus comentários.",
    "action.review_removed": "Removemos uma das suas críticas.",
    "action.account_suspended": (
        "Suspendemos a sua conta. Não poderá iniciar sessão até que a suspensão seja levantada."
    ),
    "action.account_closed": "Encerrámos a sua conta e apagámos os seus dados.",
    "action.username_reset": "Alterámos o seu nome de utilizador. O novo é {new_username}.",
    "action.review_rights_withdrawn": "Retirámos a sua possibilidade de publicar críticas.",
    "content_label": "O conteúdo em causa:",
    "reason_label": "Motivo:",
    "note_label": "Nota do moderador:",
    "from_report_yes": "Esta decisão foi tomada na sequência de uma denúncia de outro utilizador.",
    "from_report_no": "Tomámos esta decisão por iniciativa própria.",
    "automated": "Não foram usados meios automatizados para detetar o conteúdo nem para tomar esta decisão.",
    "contest": (
        "Pode contestar esta decisão escrevendo para legal@renar.app no prazo de 6 meses. Uma pessoa "
        "voltará a analisá-la e responderá com uma decisão fundamentada. Também pode recorrer aos tribunais."
    ),
    "reason.illegal_content": "O conteúdo é ilegal.",
    "reason.no_rights": f"É conteúdo que não tem o direito de partilhar ({_TERMS['pt']}).",
    "reason.harassment": f"Assedia, ameaça, insulta ou faz-se passar por outras pessoas ({_TERMS['pt']}).",
    "reason.hate_or_violence": f"É discurso de ódio, ou incita à violência ou à automutilação ({_TERMS['pt']}).",
    "reason.child_sexual_content": f"É conteúdo sexual que envolve menores ({_TERMS['pt']}; além disso, é ilegal).",
    "reason.spam": f"É spam ou publicidade, ou parte da criação de contas em massa ({_TERMS['pt']}).",
    "reason.circumvention": (
        f"Contorna limites de utilização, convites, bloqueios ou outras medidas contra abusos ({_TERMS['pt']})."
    ),
    "reason.scraping": f"Usa meios automatizados para extrair dados em massa ({_TERMS['pt']}).",
    "reason.disruption": f"Interfere com o serviço ou com o acesso de outros utilizadores ({_TERMS['pt']}).",
    "reason.no_breach": "Não encontrámos qualquer violação da lei ou dos Termos de Serviço.",
    "report.comment": "Obrigado pela sua denúncia sobre um comentário de {author}.",
    "report.review": "Obrigado pela sua denúncia sobre uma crítica de {author}.",
    "report.profile": "Obrigado pela sua denúncia sobre o perfil de {author}.",
    "outcome.removed": "Analisámo-la e removemos o conteúdo.",
    "outcome.restricted": "Analisámo-la e restringimos a conta.",
    "outcome.none": "Analisámo-la e não tomámos qualquer medida.",
    "contest_reporter": (
        "Se não concordar, pode contestar esta decisão escrevendo para legal@renar.app no prazo de 6 meses. "
        "Uma pessoa voltará a analisá-la. Também pode recorrer aos tribunais."
    ),
    "signature": "A equipa do Renar",
}

ES = {
    "subject_user": "Renar: una decisión de moderación sobre tu cuenta",
    "subject_reporter": "Renar: el resultado de tu denuncia",
    "hello": "Hola, {username}:",
    "action.comment_removed": "Hemos eliminado uno de tus comentarios.",
    "action.review_removed": "Hemos eliminado una de tus reseñas.",
    "action.account_suspended": (
        "Hemos suspendido tu cuenta. No podrás iniciar sesión hasta que se levante la suspensión."
    ),
    "action.account_closed": "Hemos cerrado tu cuenta y borrado sus datos.",
    "action.username_reset": "Hemos cambiado tu nombre de usuario. El nuevo es {new_username}.",
    "action.review_rights_withdrawn": "Hemos retirado tu posibilidad de publicar reseñas.",
    "content_label": "El contenido afectado:",
    "reason_label": "Motivo:",
    "note_label": "Nota del moderador:",
    "from_report_yes": "Esta decisión se tomó a raíz de una denuncia de otro usuario.",
    "from_report_no": "Tomamos esta decisión por iniciativa propia.",
    "automated": "No se usaron medios automatizados para detectar el contenido ni para tomar esta decisión.",
    "contest": (
        "Puedes recurrir esta decisión escribiendo a legal@renar.app en un plazo de 6 meses. Una persona "
        "la revisará de nuevo y te responderá con una decisión motivada. También puedes acudir a los tribunales."
    ),
    "reason.illegal_content": "El contenido es ilegal.",
    "reason.no_rights": f"Es contenido que no tienes derecho a compartir ({_TERMS['es']}).",
    "reason.harassment": f"Acosa, amenaza, insulta o suplanta a otras personas ({_TERMS['es']}).",
    "reason.hate_or_violence": f"Es discurso de odio o incita a la violencia o a autolesionarse ({_TERMS['es']}).",
    "reason.child_sexual_content": f"Es contenido sexual que implica a menores ({_TERMS['es']}; además es ilegal).",
    "reason.spam": f"Es spam o publicidad, o parte de la creación masiva de cuentas ({_TERMS['es']}).",
    "reason.circumvention": (
        f"Elude los límites de uso, las invitaciones, los bloqueos u otras medidas contra el abuso ({_TERMS['es']})."
    ),
    "reason.scraping": f"Usa medios automatizados para extraer datos de forma masiva ({_TERMS['es']}).",
    "reason.disruption": (
        f"Interfiere en el funcionamiento del servicio o en el acceso de otros usuarios ({_TERMS['es']})."
    ),
    "reason.no_breach": "No encontramos ningún incumplimiento de la ley ni de los Términos del servicio.",
    "report.comment": "Gracias por tu denuncia sobre un comentario de {author}.",
    "report.review": "Gracias por tu denuncia sobre una reseña de {author}.",
    "report.profile": "Gracias por tu denuncia sobre el perfil de {author}.",
    "outcome.removed": "La hemos revisado y hemos eliminado el contenido.",
    "outcome.restricted": "La hemos revisado y hemos restringido la cuenta.",
    "outcome.none": "La hemos revisado y no hemos tomado ninguna medida.",
    "contest_reporter": (
        "Si no estás de acuerdo, puedes recurrir esta decisión escribiendo a legal@renar.app en un plazo de "
        "6 meses. Una persona la revisará de nuevo. También puedes acudir a los tribunales."
    ),
    "signature": "El equipo de Renar",
}

EO = {
    "subject_user": "Renar: moderiga decido pri via konto",
    "subject_reporter": "Renar: la rezulto de via raporto",
    "hello": "Saluton, {username},",
    "action.comment_removed": "Ni forigis unu el viaj komentoj.",
    "action.review_removed": "Ni forigis unu el viaj recenzoj.",
    "action.account_suspended": "Ni suspendis vian konton. Vi ne povos ensaluti ĝis la suspendo estos nuligita.",
    "action.account_closed": "Ni fermis vian konton kaj forigis ĝiajn datumojn.",
    "action.username_reset": "Ni ŝanĝis vian uzantnomon. Via nova uzantnomo estas {new_username}.",
    "action.review_rights_withdrawn": "Ni malpermesis al vi publikigi recenzojn.",
    "content_label": "La koncerna enhavo:",
    "reason_label": "Kial:",
    "note_label": "Noto de la moderiganto:",
    "from_report_yes": "Ĉi tiu decido sekvis raporton de alia uzanto.",
    "from_report_no": "Ni faris ĉi tiun decidon laŭ nia propra iniciato.",
    "automated": "Neniuj aŭtomataj rimedoj estis uzataj por trovi la enhavon aŭ por fari ĉi tiun decidon.",
    "contest": (
        "Vi povas kontesti ĉi tiun decidon skribante al legal@renar.app ene de 6 monatoj. Homo denove "
        "ekzamenos ĝin kaj respondos per motivita decido. Vi ankaŭ povas iri al tribunalo."
    ),
    "reason.illegal_content": "La enhavo estas kontraŭleĝa.",
    "reason.no_rights": f"Ĝi estas enhavo, kiun vi ne rajtas dividi ({_TERMS['eo']}).",
    "reason.harassment": f"Ĝi ĉikanas, minacas, insultas aŭ imitas aliajn ({_TERMS['eo']}).",
    "reason.hate_or_violence": f"Ĝi estas malama parolo, aŭ instigas al perforto aŭ memdamaĝo ({_TERMS['eo']}).",
    "reason.child_sexual_content": f"Ĝi estas seksa enhavo pri neplenaĝuloj ({_TERMS['eo']}; ankaŭ kontraŭleĝa).",
    "reason.spam": f"Ĝi estas spamo aŭ reklamo, aŭ parto de amasa kreado de kontoj ({_TERMS['eo']}).",
    "reason.circumvention": (
        f"Ĝi preteriras uzlimojn, invitojn, blokojn aŭ aliajn kontraŭmisuzajn rimedojn ({_TERMS['eo']})."
    ),
    "reason.scraping": f"Ĝi uzas aŭtomatajn rimedojn por amase elkopii datumojn ({_TERMS['eo']}).",
    "reason.disruption": f"Ĝi malhelpas la servon aŭ la aliron de aliaj uzantoj al ĝi ({_TERMS['eo']}).",
    "reason.no_breach": "Ni trovis nenian malobservon de la leĝo aŭ de la Servaj Kondiĉoj.",
    "report.comment": "Dankon pro via raporto pri komento de {author}.",
    "report.review": "Dankon pro via raporto pri recenzo de {author}.",
    "report.profile": "Dankon pro via raporto pri la profilo de {author}.",
    "outcome.removed": "Ni ekzamenis ĝin kaj forigis la enhavon.",
    "outcome.restricted": "Ni ekzamenis ĝin kaj limigis la konton.",
    "outcome.none": "Ni ekzamenis ĝin kaj faris nenion.",
    "contest_reporter": (
        "Se vi malkonsentas, vi povas kontesti ĉi tiun decidon skribante al legal@renar.app ene de 6 monatoj. "
        "Homo denove ekzamenos ĝin. Vi ankaŭ povas iri al tribunalo."
    ),
    "signature": "La teamo de Renar",
}

TEXTS: dict[str, dict[str, str]] = {"en": EN, "gl": GL, "pt": PT, "es": ES, "eo": EO}


def text_for(language: str | None) -> dict[str, str]:
    """The wording for ``language``, English when it isn't an app language."""
    return TEXTS.get(language or "en", EN)
