import cron from 'node-cron';
import messageRepository from './storage/messageRepository';


// Schedule tasks to be run on the server.
cron.schedule('*/30 * * * *', () => {
    console.log('Ping databse');

    messageRepository.ping().then((res) => {
        console.log('Ping database success');
    })

});

export default cron;