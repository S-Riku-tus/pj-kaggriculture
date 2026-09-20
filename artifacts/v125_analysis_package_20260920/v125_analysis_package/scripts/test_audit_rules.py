"""Internal auditor tests, NOT proof of equivalence to the official engine."""
import copy
import unittest
from audit_engine import PRODUCTS, market, units

def fixture():
    f = {'farmer':[4,4], 'hands':[[5,4]], 'hires_today':1,
         'tiles':[[None for _ in range(10)] for _ in range(10)],
         'money':100000, 'unlocked_quadrants':['NW']}
    p = {'shed':{}, 'seeds':{'WHEAT':1}, 'inventories':[{},{}]}
    return f,p

class AuditRuleTests(unittest.TestCase):
    def test_same_slot_quotes_are_symmetric(self):
        f,p=fixture();p['shed']['WHEAT']=8
        farms=[copy.deepcopy(f),copy.deepcopy(f)]
        prs=[copy.deepcopy(p),copy.deepcopy(p)]
        inv={k:10000 for k in PRODUCTS}
        actions=[{'market':[['SELL','WHEAT',8]]} for _ in range(2)]
        market(farms,prs,actions,inv)
        self.assertEqual(farms[0]['money'],farms[1]['money'])
        self.assertEqual(inv['WHEAT'],10016)
    def test_immediate_buy_sell_round_trip(self):
        f,p=fixture();f2,p2=fixture();inv={k:10000 for k in PRODUCTS}
        market([f,f2],[p,p2],[{'market':[['BUY_PRODUCT','WHEAT',8],['SELL','WHEAT',8]]},{}],inv)
        self.assertEqual(f['money'],100000)
        self.assertEqual(inv['WHEAT'],10000)
    def test_floor_sale_does_not_increase_supply(self):
        f,p=fixture();f2,p2=fixture();p['shed']['WOOL']=6
        inv={k:10000 for k in PRODUCTS};inv['WOOL']=20000
        market([f,f2],[p,p2],[{'market':[['SELL','WOOL',6]]},{}],inv)
        self.assertEqual(f['money'],100006)
        self.assertEqual(inv['WOOL'],20000)
    def test_atomic_seed_shortage_cancels_all_requests(self):
        f,p=fixture();ev=units(f,p,{'farmer':['PLANT','WHEAT'],
                                  'hands':[['PLANT','WHEAT']]},0)
        self.assertEqual(p['seeds']['WHEAT'],1)
        self.assertTrue(all(e.get('reason')=='atomic_seed_shortage' for e in ev))
        self.assertIsNone(f['tiles'][4][4])
        self.assertIsNone(f['tiles'][4][5])
    def test_place_preserves_excess_but_drop_discards(self):
        f,p=fixture();p['shed']['WHEAT']=95;p['inventories'][0]['WHEAT']=20
        units(f,p,{'farmer':['PLACE','WHEAT',20]},0)
        self.assertEqual(p['shed']['WHEAT'],100)
        self.assertEqual(p['inventories'][0]['WHEAT'],15)
        ev=units(f,p,{'farmer':['DROP']},0)
        self.assertEqual(p['inventories'][0],{})
        self.assertEqual(ev[0]['overflow']['WHEAT'],15)

if __name__=='__main__':
    unittest.main()
