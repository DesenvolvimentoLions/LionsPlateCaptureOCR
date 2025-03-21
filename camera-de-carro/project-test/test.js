import { ocrSpace } from 'ocr-space-api-wrapper';
import fs from 'fs';

const imagePath = `./cam2_20250321-114148.png`;

function convertImageToBase64(imagePath) {
    return new Promise((resolve, reject) => {
      fs.readFile(imagePath, (err, data) => {
        if (err) {
          reject("Erro ao ler o arquivo:", err);
          return;
        }
  
        // Converte para base64
        const base64Image = data.toString('base64');
  
        // Adiciona o prefixo data:image/png;base64, para imagens PNG
        const base64StringWithPrefix = `data:image/png;base64,${base64Image}`;
        
        // Resolve com o valor Base64
        resolve(base64StringWithPrefix);
      });
    });
  }
(async () => {
    try {
        await convertImageToBase64(imagePath)
            .then(async x => {
                const res1 = await ocrSpace(x, {
                     apiKey: 'K89140021688957'
                });

                console.log(res1)
            })

        // const res1 = await ocrSpace(`data:image/png;base64`, {
        //     apiKey: 'K89140021688957'
        // })
    
        // console.log(res1);
    } catch(error) {
        console.log(error)
    }
})();