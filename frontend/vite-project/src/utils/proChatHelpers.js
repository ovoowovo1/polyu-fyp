import i18n from '../i18n/config.js';
export const generateWelcomeMessage = (documentCount, selectedCount = 0) => {
    if (documentCount === 0) {
        return i18n.t('chat.welcomeNoDocuments');
    }

    let baseMessage = i18n.t('chat.welcomeWithDocuments', { count: documentCount });

    if (selectedCount > 0 && selectedCount < documentCount) {
        baseMessage += `\n\n${i18n.t('chat.welcomeSelectedPartial', { count: selectedCount })}`;
    } else if (selectedCount === documentCount && documentCount > 1) {
        baseMessage += `\n\n${i18n.t('chat.welcomeSelectedAll')}`;
    } else {
        baseMessage += `\n\n${i18n.t('chat.welcomeNoSelection')}`;
    }

    return `${baseMessage}\n\n${i18n.t('chat.welcomeAskQuestions')}`;
};
