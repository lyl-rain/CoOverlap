"""Transaction fault injection on fake sysfs only; no GPU, root or real scope."""
import tempfile,unittest,json
from pathlib import Path
from unittest.mock import Mock,patch
import m1_clock_scope as scope

def fake_nodes(root):
    for _,b,mn,mx,av,cur,target in scope.NODES:
        p=root/b.lstrip('/');p.mkdir(parents=True)
        for k,v in [(mn,'1'),(mx,str(target)),(av,'1 '+str(target)),(cur,'1')]: (p/k).write_text(v)

class Recovery(unittest.TestCase):
    def test_apply_return_gap_restores_current_transaction(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);fake_nodes(root)
            for i,(_,b,mn,_,_,_,_) in enumerate(scope.NODES):(root/b.lstrip('/')/mn).write_text(str(10+i))
            before=scope.state(root);original_apply=scope.apply;original_restore=scope.restore;lib=Mock();lib.prctl.return_value=0
            def checked_restore(path,actual_root):
                self.assertNotEqual(Path(actual_root).resolve(),Path('/'))
                self.assertEqual(Path(actual_root).resolve(),root.resolve())
                return original_restore(path,actual_root)
            def interrupted(snapshot,transaction):
                original_apply(snapshot,root,transaction)
                self.assertTrue(all(r['min']==r['target'] for r in scope.state(root)))
                raise InterruptedError('AFTER_APPLY_RETURN_BEFORE_NEXT_STATEMENT')
            # Inject only the fake-root default; execute the real transaction
            # ownership/recovery logic and the real restore on all five nodes.
            with patch.object(scope.SnapshotTransaction.recover,'__defaults__',(root,)),patch.object(scope.ctypes,'CDLL',return_value=lib),patch.object(scope,'apply',side_effect=interrupted),patch.object(scope,'restore',side_effect=checked_restore) as restored,patch.object(scope.subprocess,'Popen') as started:
                with self.assertRaises(InterruptedError):scope.run_scope(root/'snapshot.json','unused')
                restored.assert_called_once();started.assert_not_called()
            self.assertEqual(scope.state(root),before)
    def test_existing_snapshot_rejected_without_restore(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'snapshot.json';p.write_text('OLD_SNAPSHOT_DO_NOT_TOUCH')
            with patch.object(scope,'apply') as applied,patch.object(scope,'restore') as restored:
                with self.assertRaises(FileExistsError):scope.run_scope(p,'unused')
                applied.assert_not_called();restored.assert_not_called()
            self.assertEqual(p.read_text(),'OLD_SNAPSHOT_DO_NOT_TOUCH')
    def test_failure_before_snapshot_does_not_restore(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'snapshot.json';lib=Mock();lib.prctl.return_value=0
            with patch.object(scope.ctypes,'CDLL',return_value=lib),patch.object(scope,'apply',side_effect=OSError('BEFORE_SNAPSHOT')),patch.object(scope,'restore') as restored,patch.object(scope.subprocess,'Popen') as started:
                with self.assertRaises(OSError):scope.run_scope(p,'unused')
                restored.assert_not_called();started.assert_not_called()
            self.assertFalse(p.exists())
    def test_setting_failure_rolls_back_only_new_snapshot(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);fake_nodes(root);before=scope.state(root);original=Path.write_text;raised=[False]
            def write(p,v,*a,**kw):
                if str(p).endswith('policy4/scaling_min_freq') and v=='2201600' and not raised[0]:raised[0]=True;raise OSError('SET_FAILURE')
                return original(p,v,*a,**kw)
            with patch.object(Path,'write_text',write):
                with self.assertRaises(OSError):scope.apply(root/'new.json',root)
            self.assertEqual(scope.state(root),before)
    def test_racing_other_file_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'snapshot.json';tx=scope.SnapshotTransaction(p);p.write_text('{}')
            with self.assertRaises(FileExistsError):tx.persist([])
            with patch.object(scope,'restore') as restored:self.assertFalse(tx.recover());restored.assert_not_called()

if __name__=='__main__':unittest.main(verbosity=2)
