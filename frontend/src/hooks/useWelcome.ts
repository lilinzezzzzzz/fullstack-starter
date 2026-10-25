import { useQuery } from '@tanstack/react-query';
import { getHealth, getHello } from '../api/hello';

export function useWelcome() {
  return useQuery({
    queryKey: ['welcome'],
    queryFn: async ({ signal }) => {
      const [hello, health] = await Promise.all([getHello(signal), getHealth(signal)]);
      if (health.status !== 'ok' || health.database !== 'ok') {
        throw new Error('后端尚未就绪');
      }
      return { hello, health };
    },
  });
}
