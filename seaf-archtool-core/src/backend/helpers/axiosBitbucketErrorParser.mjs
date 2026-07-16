import axios from 'axios';

export const parseAxiosBitbucketError = (error) => {
    if (axios.isAxiosError(error)) {
        // Если это ошибка axios
        const status = error.response?.status || 0;
        const statusText = error.response?.statusText || 'Unknown Status';
        const message = error.response?.data?.errors?.[0]?.message ||
            error.message ||
            'Unknown error occurred';

        return {
            status,
            statusText,
            message,
            data: error.response?.data,
            isAxiosError: true
        };
    } else if (error instanceof Error) {
        // Если это обычная ошибка JS
        return {
            status: 400,
            statusText: 'Client Error',
            message: error.message,
            isAxiosError: false
        };
    } else {
        // Если это что-то еще
        return {
            status: 400,
            statusText: 'Unknown Error',
            message: String(error),
            isAxiosError: false
        };
    }
};
