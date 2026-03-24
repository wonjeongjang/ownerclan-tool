import bcrypt, pybase64, time, requests
from dotenv import load_dotenv
import os
load_dotenv()

client_id = os.getenv('SMARTSTORE_CLIENT_ID')
client_secret = os.getenv('SMARTSTORE_CLIENT_SECRET')

timestamp = int(time.time() * 1000)
password = client_id + '_' + str(timestamp)
hashed = bcrypt.hashpw(password.encode('utf-8'), client_secret.encode('utf-8'))
client_secret_sign = pybase64.standard_b64encode(hashed).decode('utf-8')

token_response = requests.post(
    'https://api.commerce.naver.com/external/v1/oauth2/token',
    headers={'Content-Type': 'application/x-www-form-urlencoded'},
    data={'client_id': client_id, 'timestamp': timestamp, 'client_secret_sign': client_secret_sign, 'grant_type': 'client_credentials', 'type': 'SELF'}
)
token = token_response.json().get('access_token')
print('토큰:', token[:20])

for pay_type in ['PREPAYED', 'PREPAY', 'COLLECT', 'FREE']:
    r = requests.post(
        'https://api.commerce.naver.com/external/v2/products',
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        json={
            'originProduct': {
                'statusType': 'SALE', 'saleType': 'NEW',
                'leafCategoryId': '50003582', 'name': '테스트',
                'images': {'representativeImage': {'url': 'https://shop-phinf.pstatic.net/20260318_212/17738142324012oOYp_JPEG/107947081544281244_733735921.jpg'}},
                'detailContent': '테스트', 'salePrice': 10000, 'stockQuantity': 10,
                'deliveryInfo': {
                    'deliveryType': 'DELIVERY', 'deliveryAttributeType': 'NORMAL',
                    'deliveryBundleGroupUsable': False, 'deliveryCompany': 'CJGLS',
                    'deliveryFee': {'deliveryFeeType': 'PAID', 'baseFee': 3000, 'deliveryFeePayType': pay_type},
                    'claimDeliveryInfo': {'returnDeliveryFee': 3000, 'exchangeDeliveryFee': 3000}
                },
                'detailAttribute': {
                    'taxType': 'TAX', 'minorPurchasable': True,
                    'originAreaInfo': {'originNation': '04', 'originNationName': '중국', 'originAreaCode': '04', 'content': '중국'},
                    'afterServiceInfo': {'afterServiceTelephoneNumber': '070-0000-0000', 'afterServiceGuideContent': '판매자 문의'},
                    'productInfoProvidedNotice': {
                        'productInfoProvidedNoticeType': 'ETC',
                        'etc': {'itemName': '상세페이지 참조', 'modelName': '상세페이지 참조', 'manufacturer': '상세페이지 참조',
                                'customerServicePhoneNumber': '070-0000-0000', 'returnCostReason': '판매자 문의',
                                'noRefundReason': '판매자 문의', 'qualityAssuranceStandard': '판매자 문의',
                                'compensationProcedure': '판매자 문의', 'troubleShootingContents': '판매자 문의'}
                    }
                }
            },
            'smartstoreChannelProduct': {'naverShoppingRegistration': False, 'channelProductDisplayStatusType': 'ON'}
        }
    )
    print(f'{pay_type}: {r.status_code} - {r.text[:200]}')

cd ownerclan_tool
streamlit run app.py